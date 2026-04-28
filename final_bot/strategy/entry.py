# strategy/entry.py

import uuid
import asyncio
import time
from strategy.trade_logger import TradeLogger
import copy
from strategy.recovery import run_startup_recovery
from strategy.trade_context import TradeContext
from strategy.monitor import monitor_trade
from config import MAX_DIVERGENCE_ENTRY
from config import (
    ENTRY_INTERVAL
)

from strategy.globals import (
    ACTIVE_TRADES,
    COOLDOWN, 
    ENTRY_CONTROL,
    GLOBAL_KILL_SWITCH,
    TRADE_REGISTRY,
    MAX_REGISTRY_HISTORY,
    RUNTIME_CONFIG
)
ENTRY_IN_PROGRESS = False
RECOVERY_DONE = False
RECOVERY_RUNNING = False

async def entry_loop(
    private_manager,
    live_data_dict,
    sorted_top
):
    print("ENTRY LOOP ACTIVE")
    print("Sorted candidates:", list(sorted_top.keys())[:3])
    
    global ENTRY_IN_PROGRESS
    global RECOVERY_DONE, RECOVERY_RUNNING

    while True:

        if GLOBAL_KILL_SWITCH.active:
            print("🚨 GLOBAL KILL SWITCH ACTIVE")
            await asyncio.sleep(ENTRY_INTERVAL)
            continue

        if not private_manager.ready:
            await asyncio.sleep(ENTRY_INTERVAL)
            continue

        if not RECOVERY_DONE and not RECOVERY_RUNNING:
            RECOVERY_RUNNING = True
            await run_startup_recovery(private_manager, live_data_dict)
            RECOVERY_DONE = True
            continue

        if ENTRY_IN_PROGRESS:
            await asyncio.sleep(ENTRY_INTERVAL)
            continue

        if len(ACTIVE_TRADES) >= RUNTIME_CONFIG.max_active_trades:
            await asyncio.sleep(ENTRY_INTERVAL)
            continue
        
        if not sorted_top:
            await asyncio.sleep(ENTRY_INTERVAL)
            continue

        candidate = None
        now = time.time()

        # bounded iteration
        for symbol in sorted_top.keys():

            if symbol in ACTIVE_TRADES:

                continue

            if symbol in COOLDOWN:
                if now - COOLDOWN[symbol] < RUNTIME_CONFIG.cooldown_seconds:
                    continue

            if not pre_entry_validation(symbol, live_data_dict, sorted_top):
                # print("rejected:",symbol)
                continue

            candidate = symbol
            break

        if candidate is None:
            await asyncio.sleep(ENTRY_INTERVAL)
            continue

        ENTRY_IN_PROGRESS = True

        try:
            await handle_entry(
                candidate,
                private_manager,
                live_data_dict
            )
        finally:
            ENTRY_IN_PROGRESS = False

        await asyncio.sleep(ENTRY_INTERVAL)

def determine_trade_sides(data):

    ku_funding = float(data["kucoin"]["funding_rate_decimal"]["value"])
    bb_funding = float(data["bybit"]["funding_rate_decimal"]["value"])

    if abs(ku_funding) > abs(bb_funding):
        dominant = "kucoin"
        dominant_value = ku_funding
    else:
        dominant = "bybit"
        dominant_value = bb_funding

    if dominant == "kucoin":
        if ku_funding > 0:
            ku_side = "sell"
            bb_side = "Buy"
        else:
            ku_side = "buy"
            bb_side = "Sell"
    else:
        if bb_funding > 0:
            bb_side = "Sell"
            ku_side = "buy"
        else:
            bb_side = "Buy"
            ku_side = "sell"

    return bb_side, ku_side, dominant, dominant_value

def margin_guard(base_exposure, data, bb_side, ku_side, private_manager):

    leverage = RUNTIME_CONFIG.leverage
    allowed_percent = RUNTIME_CONFIG.max_margin_usage_percent

    price_b = execution_price(data, "bybit", bb_side)
    price_k = execution_price(data, "kucoin", ku_side)

    notional_b = base_exposure * price_b
    notional_k = base_exposure * price_k

    margin_b = notional_b / leverage
    margin_k = notional_k / leverage

    balance_b = private_manager.bybit.get_balance()
    balance_k = private_manager.kucoin.get_balance()

    allowed_b = balance_b * allowed_percent
    allowed_k = balance_k * allowed_percent

    if margin_b > allowed_b or margin_k > allowed_k:

        print("❌ Margin guard rejected trade")
        print("Bybit required:", margin_b, "Allowed:", allowed_b)
        print("KuCoin required:", margin_k, "Allowed:", allowed_k)

        return False, notional_b, notional_k

    return True, notional_b, notional_k

def build_legs(bb_side, ku_side, bb_qty, ku_qty, sym_bybit, sym_kucoin, mult_b, mult_k, notional_b, notional_k, res_long=None, res_short=None):

    if bb_side.lower() == "buy":

        long_leg = {
            "exchange": "bybit",
            "engine": sym_bybit,
            "side": bb_side,
            "qty": bb_qty,
            "multiplier": mult_b,
            "notional": notional_b,
            "entry_price": res_long["avg_price"] if res_long else 0
        }

        short_leg = {
            "exchange": "kucoin",
            "engine": sym_kucoin,
            "side": ku_side,
            "qty": ku_qty,
            "multiplier": mult_k,
            "notional": notional_k,
            "entry_price": res_short["avg_price"] if res_short else 0
        }

    else:

        long_leg = {
            "exchange": "kucoin",
            "engine": sym_kucoin,
            "side": ku_side,
            "qty": ku_qty,
            "multiplier": mult_k,
            "notional": notional_k,
            "entry_price": res_short["avg_price"] if res_short else 0
        }

        short_leg = {
            "exchange": "bybit",
            "engine": sym_bybit,
            "side": bb_side,
            "qty": bb_qty,
            "multiplier": mult_b,
            "notional": notional_b,
            "entry_price": res_long["avg_price"]  if res_long else 0
        }

    return long_leg, short_leg


async def place_hedge_orders(long_leg, short_leg, live_data_dict, symbol):

    MAX_ATTEMPTS = 20
    AGGRESSION = 0.5
    LOOP_SLEEP = 0.03
    MAX_IMBALANCE_RATIO = 0.25

    long_engine = long_leg["engine"]
    short_engine = short_leg["engine"]

    long_side = long_leg["side"]
    short_side = short_leg["side"]

    target_long = float(long_leg["qty"])
    target_short = float(short_leg["qty"])

    filled_long = 0.0
    filled_short = 0.0

    avg_long_cost = 0.0
    avg_short_cost = 0.0

    attempts = 0

    last_long_result = None
    last_short_result = None

    while True:

        remaining_long = max(target_long - filled_long, 0)
        remaining_short = max(target_short - filled_short, 0)

        if remaining_long <= 0 and remaining_short <= 0:
            break

        if attempts >= MAX_ATTEMPTS:
            break

        data = live_data_dict[symbol]

        # -------------------------
        # READ ORDERBOOK
        # -------------------------

        if long_leg["exchange"] == "bybit":
            best_price_long = float(
                data["bybit"]["best_ask_price"]["value"]
                if long_side.lower() == "buy"
                else data["bybit"]["best_bid_price"]["value"]
            )

            best_size_long = float(
                data["bybit"]["best_ask_size"]["value"]
                if long_side.lower() == "buy"
                else data["bybit"]["best_bid_size"]["value"]
            )
        else:
            best_price_long = float(
                data["kucoin"]["best_ask_price"]["value"]
                if long_side.lower() == "buy"
                else data["kucoin"]["best_bid_price"]["value"]
            )

            best_size_long = float(
                data["kucoin"]["best_ask_size"]["value"]
                if long_side.lower() == "buy"
                else data["kucoin"]["best_bid_size"]["value"]
            )

        if short_leg["exchange"] == "bybit":
            best_price_short = float(
                data["bybit"]["best_ask_price"]["value"]
                if short_side.lower() == "buy"
                else data["bybit"]["best_bid_price"]["value"]
            )

            best_size_short = float(
                data["bybit"]["best_ask_size"]["value"]
                if short_side.lower() == "buy"
                else data["bybit"]["best_bid_size"]["value"]
            )
        else:
            best_price_short = float(
                data["kucoin"]["best_ask_price"]["value"]
                if short_side.lower() == "buy"
                else data["kucoin"]["best_bid_price"]["value"]
            )

            best_size_short = float(
                data["kucoin"]["best_ask_size"]["value"]
                if short_side.lower() == "buy"
                else data["kucoin"]["best_bid_size"]["value"]
            )

        # -------------------------
        # COMPUTE ORDER SIZE
        # -------------------------

        order_long = min(
            remaining_long,
            best_size_long * AGGRESSION
        )

        order_short = min(
            remaining_short,
            best_size_short * AGGRESSION
        )

        if order_long <= 0 and order_short <= 0:
            await asyncio.sleep(LOOP_SLEEP)
            attempts += 1
            continue

        # -------------------------
        # IMBALANCE GUARD
        # -------------------------

        imbalance = abs(filled_long - filled_short) / max(
            max(filled_long, filled_short), 1
        )

        if imbalance > MAX_IMBALANCE_RATIO:

            if filled_long > filled_short:
                order_long = 0
            else:
                order_short = 0

        # -------------------------
        # PLACE IOC ORDERS
        # -------------------------

        res_long, res_short = await asyncio.gather(

            long_engine.place_limit_ioc(
                side=long_side,
                size=float(order_long),
                price=float(best_price_long),
                leverage=RUNTIME_CONFIG.leverage
            ) if order_long > 0 else asyncio.sleep(0),

            short_engine.place_limit_ioc(
                side=short_side,
                size=float(order_short),
                price=float(best_price_short),
                leverage=RUNTIME_CONFIG.leverage
            ) if order_short > 0 else asyncio.sleep(0)
        )

        if order_long > 0:
            last_long_result = res_long
            filled = float(res_long.get("filled_size", 0))
            price = float(res_long.get("avg_price", 0))

            filled_long += filled
            avg_long_cost += filled * price

        if order_short > 0:
            last_short_result = res_short
            filled = float(res_short.get("filled_size", 0))
            price = float(res_short.get("avg_price", 0))

            filled_short += filled
            avg_short_cost += filled * price

        attempts += 1

        await asyncio.sleep(LOOP_SLEEP)

    # -------------------------
    # BUILD FINAL RESULT
    # -------------------------

    avg_price_long = (
        avg_long_cost / filled_long if filled_long > 0 else 0
    )

    avg_price_short = (
        avg_short_cost / filled_short if filled_short > 0 else 0
    )

    result_long = {
        "success": filled_long > 0,
        "filled_size": filled_long,
        "avg_price": avg_price_long,
        "raw": last_long_result
    }

    result_short = {
        "success": filled_short > 0,
        "filled_size": filled_short,
        "avg_price": avg_price_short,
        "raw": last_short_result
    }

    return result_long, result_short


def calculate_divergence(public_data):
        try:
            mark_bybit = float(public_data["bybit"]["mark_price"]["value"])
            mark_kucoin = float(public_data["kucoin"]["mark_price"]["value"])
        except Exception:
            return None

        if mark_bybit <= 0 or mark_kucoin <= 0:
            return None

        reference = (mark_bybit + mark_kucoin) / 2
        divergence = abs(mark_bybit - mark_kucoin) / reference

        return divergence

async def handle_entry(
    symbol,
    private_manager,
    live_data_dict
):

    # print("inside handle_entry ")
    bybit = private_manager.bybit
    kucoin = private_manager.kucoin
    data = live_data_dict[symbol]
    # print("-----------------------------------------------------------------------")
    # print("bybit amount:",bybit.get_account_state())
    # print("kucoin amount: ",kucoin.get_account_state())
    # print("-----------------------------------------------------------------------")
    
    bb_side, ku_side, dominant, dominant_value = determine_trade_sides(data)
    
    qty_info = compute_qty(symbol, private_manager, live_data_dict,bb_side)
    if not qty_info:
        return


    # print("quantity calculated ")
    ku_qty = qty_info["kucoin_contracts"]
    bb_qty = qty_info["bybit_contracts"]
    base_exposure = qty_info["base_exposure"]
    mult_k = qty_info["mult_k"]
    mult_b = qty_info["mult_b"]

    # =========================
    # MARGIN SAFETY CHECK
    # =========================

    ok, notional_b, notional_k = margin_guard(
        base_exposure,
        data,
        bb_side,
        ku_side,
        private_manager
    )

    if not ok:
        return
    
    if not ENTRY_CONTROL.allowed :
    # print("🚫 ENTRY BLOCKED BY MANUAL TOGGLE (NO REST, NO WS)")
        return

    logger = TradeLogger(symbol)

    bb_real_name = live_data_dict[symbol]["bybit"]["original_name"]["value"]
    ku_real_name = live_data_dict[symbol]["kucoin"]["original_name"]["value"]
    # 1️⃣ add symbol
    try:
        logger.log_event("add_symbol_attempt", exchange="bybit", symbol=bb_real_name)
        logger.log_event("add_symbol_attempt", exchange="kucoin", symbol=ku_real_name)

        sym_bybit = await bybit.add_symbol(bb_real_name)
        sym_kucoin = await kucoin.add_symbol(ku_real_name)
        
        # Determine which engine is LONG and which is SHORT
        long_leg, short_leg = build_legs(
            bb_side,
            ku_side,
            bb_qty,
            ku_qty,
            sym_bybit,
            sym_kucoin,
            mult_b,
            mult_k,
            notional_b,
            notional_k
        )

        sym_long = long_leg["engine"]
        sym_short = short_leg["engine"]

        long_exchange = long_leg["exchange"]
        short_exchange = short_leg["exchange"]

        long_side = long_leg["side"]
        short_side = short_leg["side"]

        long_qty = long_leg["qty"]
        short_qty = short_leg["qty"]

        logger.log_event("add_symbol_success", exchange="bybit")
        logger.log_event("add_symbol_success", exchange="kucoin")

    except Exception as e:
        logger.log_error("add_symbol_failed", e)
        logger.close()
        return


    trade_id = uuid.uuid4().hex

# cap registry size
    if len(TRADE_REGISTRY) >= MAX_REGISTRY_HISTORY:
        oldest_key = next(iter(TRADE_REGISTRY))
        TRADE_REGISTRY.pop(oldest_key, None)

    TRADE_REGISTRY[trade_id] = {
        "trade_id": trade_id,
        "symbol": symbol,
        "status": "PLACE_ATTEMPT",
        "created_at": time.time(),
        "engines": {
            "long": sym_long,
            "short": sym_short,
            "long_exchange": long_exchange,
            "short_exchange": short_exchange
        },
        "error": None
    }

    print("Placing hedge:", symbol, "kuQty:", ku_qty, "bbqty",bb_qty)
    # 3️⃣ place hedge
    # 3️⃣ place hedge
    logger.log_event(
        "place_market_attempt",
        long_exchange=long_exchange,
        short_exchange=short_exchange,
        long_side=long_side,
        short_side=short_side,
        long_qty=long_qty,
        short_qty=short_qty,
        leverage=RUNTIME_CONFIG.leverage
    )

    print(f"base_exposure needed : {base_exposure} \nbb qty : {bb_qty} || bb exposure: {bb_qty*mult_b} || bb_mult {mult_b} || bb min qty allowed : {data["bybit"]["min_order_qty"]["value"]} || bb margin : {notional_b/RUNTIME_CONFIG.leverage}\n ku qty : {ku_qty} || ku exposure: {ku_qty*mult_k} || ku_mult {mult_k}|| ku min qty allowed : {data["kucoin"]["min_order_qty"]["value"]} || ku margin : {notional_k/RUNTIME_CONFIG.leverage}")
    
    print(f"just before placing market, symbol:{symbol}__min qty bb: {live_data_dict[symbol]["bybit"]["min_order_qty"]["value"]}  |||| ku min qty: {live_data_dict[symbol]["kucoin"]["min_order_qty"]["value"]}")

    res_long, res_short = await place_hedge_orders(long_leg, short_leg,live_data_dict,symbol)

    # map responses to correct exchange
    responses = {
        long_leg["exchange"]: res_long,
        short_leg["exchange"]: res_short
    }


    bybit_response = responses.get("bybit")
    kucoin_response = responses.get("kucoin")

    logger.log_event(
        "place_market_response",
        bybit_response=bybit_response,
        kucoin_response=kucoin_response,
        long_exchange=long_exchange,
        short_exchange=short_exchange
    )

    # print("Entry result:", res_long, res_short)

    if not (res_long["success"] and res_short["success"]):

        TRADE_REGISTRY[trade_id]["status"] = "FAILED"
        TRADE_REGISTRY[trade_id]["error"] = "place_market_failed"

        await cleanup_failed_entry(
            sym_long,
            sym_short,
            private_manager,
            bb_real_name,
            ku_real_name,
            logger,
            reason="`place_market_failed`",
            trade_id=trade_id
        )
        return


    long_leg["entry_price"] = res_long["avg_price"]
    short_leg["entry_price"] = res_short["avg_price"]

    # ---- PARTIAL FILL LOGIC ----

    long_filled_qty = float(res_long["filled_size"])
    short_filled_qty = float(res_short["filled_size"])

    long_base_exposure = long_filled_qty * long_leg["multiplier"]
    short_base_exposure = short_filled_qty * short_leg["multiplier"]

    long_exposure_ratio = long_base_exposure / base_exposure
    short_exposure_ratio = short_base_exposure / base_exposure

    min_exposure_ratio = min(long_exposure_ratio, short_exposure_ratio)
    print(f"long_exposure_ratio:{long_exposure_ratio} || short_exposure_ratio:{short_exposure_ratio} \n min_ration: {min_exposure_ratio} || base_exposure : {base_exposure}")
    logger.log_event(
        "fill_analysis",
        long_filled_qty=long_filled_qty,
        short_filled_qty=short_filled_qty,
        base_exposure=base_exposure,
        long_base_exposure=long_base_exposure,
        short_base_exposure=short_base_exposure,
        long_exposure_ratio=long_exposure_ratio,
        short_exposure_ratio=short_exposure_ratio
    )

    if min_exposure_ratio < 0.95:
        # too low fill → abort
        await cleanup_failed_entry(sym_long, sym_short, private_manager, bb_real_name,ku_real_name,logger,reason = "partial_fill_below_hedge",trade_id=trade_id)
        return

    # If here → acceptable partial, try single retry
    remaining_long_exposure = base_exposure - long_base_exposure
    remaining_short_exposure = base_exposure - short_base_exposure

    remaining_long_qty = remaining_long_exposure / long_leg["multiplier"]
    remaining_short_qty = remaining_short_exposure / short_leg["multiplier"]

    if remaining_long_qty < 1e-12:
        remaining_long_qty = 0
    if remaining_short_qty < 1e-12:
        remaining_short_qty = 0
    
    if min_exposure_ratio >=0.9999:
        remaining_long_qty = 0
        remaining_short_qty =0

    # ---------- RETRY + FINAL SIZE RESOLUTION ----------

    retry_results = None

    if remaining_long_qty > 0 or remaining_short_qty > 0:

        logger.log_event(
            "retry_attempt",
            remaining_long_qty=remaining_long_qty,
            remaining_short_qty=remaining_short_qty
        )

        retry_results = await asyncio.gather(
            sym_long.place_market(
                side=long_leg["side"],
                size=float(remaining_long_qty),
                leverage=RUNTIME_CONFIG.leverage
            ) if remaining_long_qty > 0 else asyncio.sleep(0),

            sym_short.place_market(
                side=short_leg["side"],
                size=float(remaining_short_qty),
                leverage=RUNTIME_CONFIG.leverage
            ) if remaining_short_qty > 0 else asyncio.sleep(0)
        )

        await asyncio.sleep(0.3)

        logger.log_event("retry_response", retry_results=retry_results)

        try:
            final_long_qty = abs(float(sym_long.get_state()["size"]))
            final_short_qty = abs(float(sym_short.get_state()["size"]))
        except Exception:
            await cleanup_failed_entry(
                sym_long,
                sym_short,
                private_manager,
                bb_real_name,
                ku_real_name,
                logger,
                reason="retry_state_fetch_failed",
                trade_id=trade_id
            )
            return

    else:
        # No retry needed — trust initial fills
        final_long_qty = long_filled_qty
        final_short_qty = short_filled_qty


    final_long_base = final_long_qty * long_leg["multiplier"]
    final_short_base = final_short_qty * short_leg["multiplier"]

# relative tolerance check (percent of base_exposure)
    HEDGE_TOL_PCT = getattr(RUNTIME_CONFIG, "hedge_tolerance_pct", 0.003)  # default 0.3%
    hedge_error = abs(final_long_base - final_short_base) / (base_exposure if base_exposure != 0 else 1.0)

    logger.log_event(
        "hedge_verification",
        final_long_qty=final_long_qty,
        final_short_qty=final_short_qty,
        final_long_base=final_long_base,
        final_short_base=final_short_base,
        hedge_error=hedge_error,
        tolerance_pct=HEDGE_TOL_PCT
    )

    if hedge_error > HEDGE_TOL_PCT:
        await cleanup_failed_entry(sym_long, sym_short, private_manager, bb_real_name,ku_real_name,logger,reason = "hedge_quantity_mismatch",trade_id=trade_id)
        return

    entry_div = calculate_divergence(live_data_dict[symbol])

    bb_funding = float(live_data_dict[symbol]["bybit"]["funding_rate_decimal"]["value"])
    ku_funding = float(live_data_dict[symbol]["kucoin"]["funding_rate_decimal"]["value"])

    # 4️⃣ create trade
    trade = TradeContext(
        symbol_name=symbol,
        long_engine=sym_long,
        short_engine=sym_short,
        long_exchange=long_exchange,
        short_exchange=short_exchange,
        bb_qty=bb_qty,
        ku_qty = ku_qty,
        bb_notional = notional_b,
        ku_notional = notional_k,
        entry_price_long=res_long["avg_price"],
        entry_price_short=res_short["avg_price"],

        long_leg = long_leg,
        short_leg = short_leg,

        entry_dominant_exchange=dominant,
        entry_funding_sign=1 if dominant_value > 0 else -1,

        bb_funding = bb_funding,
        ku_funding = ku_funding,

        entry_funding_difference = abs(bb_funding - ku_funding),
        mult_b = mult_b,
        mult_k = mult_k,
        base_exposure = base_exposure,
        trade_id = trade_id,
        entry_div_percent = entry_div
    )

    TRADE_REGISTRY[trade_id]["status"] = "ACTIVE"
    TRADE_REGISTRY[trade_id]["trade_object"] = trade

    print("Trade created:", symbol)
    trade.logger = logger
    logger.log_event("trade_context_created")
    ACTIVE_TRADES[symbol] = trade


    # 5️⃣ spawn monitor
    task = asyncio.create_task(
        monitor_trade(
            trade,
            private_manager,
            live_data_dict,
        )
    )

    trade.monitor_task = task

def pre_entry_validation(symbol, live_data_dict, sorted_top):

    # print("validating",symbol)

    if symbol not in live_data_dict:
        print("symbol not in live data",symbol)
        return False

    if symbol not in sorted_top:
        print("symbol not in sorted top dict",symbol)
        return False

    data = live_data_dict[symbol]
    sorted_data = sorted_top[symbol]

    try:
        # -------- Exchange Online Check --------
        if data["bybit"]["offline"]["value"]:
            print("bybit offline",symbol)
            return False
        if data["kucoin"]["offline"]["value"]:
            print("kucoin offline",symbol)
            return False

        # -------- Funding Diff Exists --------
        funding_diff = sorted_data["funding_rate_difference_decimal"]["value"]
        if funding_diff is None:
            print("funding diff is None:",symbol)
            return False

        # -------- Basic Market Fields --------
        if data["bybit"]["best_bid_price"]["value"] is None:
            print("bybit best bid price is none:",symbol)
            return False

        if data["bybit"]["best_ask_price"]["value"] is None:
            print("bybit best ask price is none:",symbol)
            return False

        if data["kucoin"]["best_bid_price"]["value"] is None:
            print("kucoin best bid price is none:",symbol)
            return False

        if data["kucoin"]["best_ask_price"]["value"] is None:
            print("kucoin best ask price is none:",symbol)
            return False

        # -------- Mark Prices Ready --------
        if data["bybit"]["mark_price"]["value"] is None:
            print("bybitmarkprice is none:",symbol)
            return False

        if data["kucoin"]["mark_price"]["value"] is None:
            # print("kucoin markprice is none:",symbol)
            return False

    except KeyError:
        print("keyerror:",symbol)
        return False

    # Funding threshold
    if abs(funding_diff) < RUNTIME_CONFIG.min_funding_diff:
        # print("fundng threshold too low",symbol)
        return False

    # Entry divergence filter
    mark_bybit = float(data["bybit"]["mark_price"]["value"])
    mark_kucoin = float(data["kucoin"]["mark_price"]["value"])

    reference = (mark_bybit + mark_kucoin) / 2
    divergence = abs(mark_bybit - mark_kucoin) / reference

    if divergence > MAX_DIVERGENCE_ENTRY:
        # print("divergence is too high",symbol)
        return False
    
        # -------- Earliest Funding Timing Filter --------

    next_funding_bybit = data["bybit"]["next_funding_at_utc"]["value"]
    next_funding_kucoin = data["kucoin"]["next_funding_at_utc"]["value"]

    if next_funding_bybit is None or next_funding_kucoin is None:
        print("next funding time missing:", symbol)
        return False

    # Select earliest funding timestamp
    earliest_funding = min(float(next_funding_bybit), float(next_funding_kucoin))

    time_remaining = earliest_funding - time.time()

    # Funding already passed
    if time_remaining <= 0:
        print("funding already passed:", symbol)
        return False

    # Not within 30 minutes
    if time_remaining > RUNTIME_CONFIG.time_remained_to_fund:
        # print("funding not within 30 minutes:", symbol)
        return False

    # Ensure symbol exists in both structures

    now = time.time()

    ts1 = data["bybit"]["best_bid_price"]["ts"]
    ts2 = data["kucoin"]["best_bid_price"]["ts"]
    if not ts1 or not ts2:
        print("kucoin or bybit best bid price timestmp is none",symbol)
        return False

    # if now - ts1 > 50 :
        # print("bybit best bid price timestmp is stale",symbol)
        # return False
    if now - ts2 > 50:
        print("kucoin best bid price timestmp is stale",symbol)
        return False

    # print("passed Validation:",symbol)
    return True

async def cleanup_failed_entry(
    sym_long,
    sym_short,
    private_manager,
    bb_real_name,
    ku_real_name,
    logger=None,
    reason=None,
    trade_id=None
):

    if logger:
        logger.log_event("cleanup_failed_entry_called",reason = reason)

    try:
        res_long = res_short = {"success": False}
        res_long, res_short = await asyncio.gather(
            sym_long.close_position(),
            sym_short.close_position()
        )
    except Exception as e:
        logger.log_error("cleanup_close_failed", e)

    if not res_long["success"]:
        logger.log_error("long_close_failed", sym_long, "result", res_long)
    if not res_short["success"]:
        logger.log_error("short_close_failed", sym_short, "result", res_short)

    await private_manager.bybit.remove_symbol(bb_real_name)
    await private_manager.kucoin.remove_symbol(ku_real_name)

    if trade_id and trade_id in TRADE_REGISTRY:
        TRADE_REGISTRY[trade_id]["status"] = "ABORTED"
        TRADE_REGISTRY[trade_id]["error"] = reason

    if logger:
        logger.log_event("trade_aborted")
        logger.close()

from fractions import Fraction
from math import gcd, ceil
import math

def _fraction_gcd(a: Fraction, b: Fraction) -> Fraction:
    num_gcd = gcd(a.numerator, b.numerator)
    den_lcm = abs(a.denominator * b.denominator) // gcd(a.denominator, b.denominator)
    return Fraction(num_gcd, den_lcm)

def _fraction_lcm(a: Fraction, b: Fraction) -> Fraction:
    if a == 0 or b == 0:
        return Fraction(0, 1)
    g = _fraction_gcd(a, b)
    return abs(a * b) / g

def _ceil_fraction_to_int(fr: Fraction) -> int:
    return -(-fr.numerator // fr.denominator)

def _align_contracts_to_step(contracts: Fraction, step: Fraction, minqty: Fraction) -> Fraction:
    if contracts <= minqty:
        return minqty
    steps = _ceil_fraction_to_int((contracts - minqty) / step)
    return minqty + steps * step

def execution_price(data, exchange, side):

    if exchange == "bybit":
        if side.lower() == "buy":
            return float(data["bybit"]["best_ask_price"]["value"])
        else:
            return float(data["bybit"]["best_bid_price"]["value"])

    else:
        if side.lower() == "buy":
            return float(data["kucoin"]["best_ask_price"]["value"])
        else:
            return float(data["kucoin"]["best_bid_price"]["value"])

def compute_qty(symbol, private_manager, live_data_dict, bb_side):
    """
    Safer qty computation:
      - ensures Bybit min-notional (5.05 USD) is met
      - quantizes base to lcm(base_step_k, base_step_b)
      - ceil-aligns contracts to each exchange's lot_size + min_qty
      - adaptive bumping with conservative cap (keeps values near min order qty)
    Returns: same keys your code expects (kucoin_contracts, bybit_contracts, base_exposure, mult_k, mult_b)
    """
    data = live_data_dict[symbol]

    try:
        mult_k = float(data["kucoin"]["multiplier"]["value"])
        mult_b = float(data["bybit"]["multiplier"]["value"])
        min_k_contracts = float(data["kucoin"]["min_order_qty"]["value"])
        min_b_contracts = float(data["bybit"]["min_order_qty"]["value"])
        step_k = float(data["kucoin"]["lot_size"]["value"])
        step_b = float(data["bybit"]["lot_size"]["value"])
    except Exception as e:
        print("MIN SIZE COMPUTE ERROR:", e)
        return None

    # Small, conservative knobs — move them to RUNTIME_CONFIG if you want
    HEDGE_TOL_PCT = getattr(RUNTIME_CONFIG, "hedge_tolerance_pct", 0.003)   # 0.3%
    MAX_SCALE_UP = getattr(RUNTIME_CONFIG, "qty_max_scale_up", 1.2)         # don't grow >20% by default
    MAX_ATTEMPTS = getattr(RUNTIME_CONFIG, "qty_max_attempts", 6)
    MIN_NOTIONAL_B = 5.05

    # Fractions for exact arithmetic
    f_mult_k = Fraction(mult_k).limit_denominator(10**9)
    f_mult_b = Fraction(mult_b).limit_denominator(10**9)
    f_step_k = Fraction(step_k).limit_denominator(10**9)
    f_step_b = Fraction(step_b).limit_denominator(10**9)
    f_min_k = Fraction(min_k_contracts).limit_denominator(10**9)
    f_min_b = Fraction(min_b_contracts).limit_denominator(10**9)

    # base steps and minimum base required
    base_step_k = f_mult_k * f_step_k
    base_step_b = f_mult_b * f_step_b
    min_base_k = f_min_k * f_mult_k
    min_base_b = f_min_b * f_mult_b
    desired_base = max(min_base_k, min_base_b)

    # ---- Bybit minimum notional guard ----
    if bb_side.lower() == "buy":
        execution_price_b = float(data["bybit"]["best_ask_price"]["value"])
    else:
        execution_price_b = float(data["bybit"]["best_bid_price"]["value"])

    current_notional_b = float(desired_base) * execution_price_b
    if current_notional_b < MIN_NOTIONAL_B:
        required_base_for_5 = MIN_NOTIONAL_B / execution_price_b
        desired_base = max(desired_base, Fraction(required_base_for_5).limit_denominator(10**9))

    # common base step (LCM of base step increments)
    common_base_step = _fraction_lcm(base_step_k, base_step_b)
    if common_base_step == 0:
        common_base_step = max(base_step_k, base_step_b)

    def quantize_base_to_common_unit(base: Fraction) -> Fraction:
        mult = _ceil_fraction_to_int(base / common_base_step)
        return mult * common_base_step

    current_base = quantize_base_to_common_unit(desired_base)

    # safety cap to prevent runaway scaling
    max_base = desired_base * Fraction(int(MAX_SCALE_UP * 1000000), 1000000)
    max_base = Fraction(math.ceil(float(max_base)), 1)

    attempts = 0
    while attempts < MAX_ATTEMPTS:
        attempts += 1

        # derive raw contracts for candidate base
        contracts_b = current_base / f_mult_b
        contracts_k = current_base / f_mult_k

        # ceil-align contracts to exchange step/mins
        aligned_b = _align_contracts_to_step(contracts_b, f_step_b, f_min_b)
        aligned_k = _align_contracts_to_step(contracts_k, f_step_k, f_min_k)

        final_base_b = aligned_b * f_mult_b
        final_base_k = aligned_k * f_mult_k
        final_base = max(final_base_b, final_base_k)

        hedge_error = abs(final_base_b - final_base_k) / (final_base if final_base != 0 else Fraction(1,1))

        # Accept if within tolerance OR if we bumped to satisfy min-notional (allow that)
        min_notional_satisfied = ('required_base_for_5' in locals() and float(current_base) >= float(Fraction(required_base_for_5).limit_denominator(10**9)))
        if float(hedge_error) <= HEDGE_TOL_PCT or min_notional_satisfied:
            # recompute final contracts from final_base cleanly and return
            final_contracts_b = _align_contracts_to_step(final_base / f_mult_b, f_step_b, f_min_b)
            final_contracts_k = _align_contracts_to_step(final_base / f_mult_k, f_step_k, f_min_k)
            final_long_base = final_contracts_b * f_mult_b
            final_short_base = final_contracts_k * f_mult_k
            final_base_exposure = max(final_long_base, final_short_base)
            return {
                "kucoin_contracts": float(final_contracts_k),
                "bybit_contracts": float(final_contracts_b),
                "base_exposure": float(final_base_exposure),
                "mult_k": float(f_mult_k),
                "mult_b": float(f_mult_b),
                "hedge_error": float(hedge_error),
                "attempts": attempts
            }

        # bump up and retry (small increments)
        bump = common_base_step
        if common_base_step < max(base_step_k, base_step_b):
            bump = max(base_step_k, base_step_b)
        current_base += bump

        if current_base > max_base:
            break

    # fallback best-effort
    aligned_b = _align_contracts_to_step((current_base / f_mult_b), f_step_b, f_min_b)
    aligned_k = _align_contracts_to_step((current_base / f_mult_k), f_step_k, f_min_k)
    final_base_b = aligned_b * f_mult_b
    final_base_k = aligned_k * f_mult_k
    final_base = max(final_base_b, final_base_k)
    hedge_error = abs(final_base_b - final_base_k) / (final_base if final_base != 0 else Fraction(1,1))

    return {
        "kucoin_contracts": float(aligned_k),
        "bybit_contracts": float(aligned_b),
        "base_exposure": float(final_base),
        "mult_k": float(f_mult_k),
        "mult_b": float(f_mult_b),
        "hedge_error": float(hedge_error),
        "attempts": attempts,
        "warning": "couldn't find within tolerance, returning best-effort"
    }

 