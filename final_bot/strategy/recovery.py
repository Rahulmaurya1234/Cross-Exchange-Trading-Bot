import asyncio
import time
import uuid

from strategy.globals import ACTIVE_TRADES, TRADE_REGISTRY, MAX_REGISTRY_HISTORY
from strategy.trade_logger import TradeLogger
from strategy.trade_context import TradeContext
from strategy.monitor import monitor_trade
from public.matcher import normalize_futures_symbol


# ---------------------------------------------------------
# PLACEHOLDER – REST hedge validation
# ---------------------------------------------------------

def rest_hedge_check(bybit_pos, kucoin_pos, tolerance=0.003):

    # leverage match check 

    b_lev = float(bybit_pos["full_response_dict"]["leverage"])
    k_lev = float(kucoin_pos["full_response_dict"]["leverage"])

    if abs(b_lev - k_lev) > 0.3:
        return False

    #same side exposure check 

    try:
        if bybit_pos["side"] == kucoin_pos["side"]:
            return False
    except Exception as e:
        print("error inside recovery rest hedge check passing without action :",e)
        pass

    # -----------------------
    # BYBIT BASE EXPOSURE
    # -----------------------

    base_b = float(bybit_pos["size"])


    # -----------------------
    # KUCOIN BASE EXPOSURE
    # -----------------------

    k = kucoin_pos["full_response_dict"]

    qty = abs(float(k["currentQty"]))
    entry = float(k["avgEntryPrice"])
    cost = abs(float(k["currentCost"]))

    if qty == 0 or entry == 0:
        return False

    multiplier = cost / (qty * entry)

    base_k = float(kucoin_pos["size"]) * multiplier

    print("inside rest hedge check")
    print("base_k:",base_k,"base_b:",base_b)

    # -----------------------
    # HEDGE ERROR
    # -----------------------

    denom = max(base_b, base_k)

    if denom == 0:
        return False

    hedge_error = abs(base_b - base_k) / denom

    return hedge_error <= tolerance


# ---------------------------------------------------------
# LIVE DATA HEDGE VALIDATION
# ---------------------------------------------------------

def live_data_hedge_check(symbol, bybit_pos, kucoin_pos, live_data_dict, tolerance):

    data = live_data_dict[symbol]

    mult_b = float(data["bybit"]["multiplier"]["value"])
    mult_k = float(data["kucoin"]["multiplier"]["value"])

    qty_b = float(bybit_pos["size"])
    qty_k = float(kucoin_pos["size"])

    base_b = qty_b * mult_b
    base_k = qty_k * mult_k

    print("inside live data hedge check")
    print("base_b:",base_b,"base_k:",base_k)

    hedge_error = abs(base_b - base_k) / max(base_b, base_k)
    print(hedge_error)

    return hedge_error <= tolerance


# ---------------------------------------------------------
# WAIT FOR LIVE DATA
# ---------------------------------------------------------

async def wait_for_live_data(symbol, live_data_dict):

    while True:

        data = live_data_dict.get(symbol)

        if not data:
            await asyncio.sleep(0.5)
            continue

        if data["bybit"]["best_bid_price"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        if data["kucoin"]["best_bid_price"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        if data["bybit"]["mark_price"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        if data["kucoin"]["mark_price"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        if data["kucoin"]["multiplier"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        if data["bybit"]["multiplier"]["value"] is None:
            await asyncio.sleep(0.5)
            continue

        return


# ---------------------------------------------------------
# CLOSE ORPHAN POSITION
# ---------------------------------------------------------

async def close_orphan_position(private_manager, pos):

    exchange = pos["exchange"]
    symbol = pos["symbol"]

    try:

        if exchange == "bybit":

            sym = await private_manager.bybit.add_symbol(symbol)

            full = pos.get("full_response_dict", {})

            # 🔹 initialize leverage
            lev = full.get("leverage")
            if lev:
                sym.current_leverage = int(float(lev))

            # 🔹 initialize state
            sym.state["position"] = full
            sym.state["side"] = pos["side"]
            sym.state["size"] = pos["size"]
            sym.state["entry_price"] = pos["entry_price"]
            sym.state["liquidation_price"] = full.get("liqPrice")
            sym.state["unrealized_pnl"] = float(full.get("unrealisedPnl",0))

            res = await sym.close_position()

            print("orphan closing response , bybit me ", res)

            await private_manager.bybit.remove_symbol(symbol)

        else:

            sym = await private_manager.kucoin.add_symbol(symbol)

            res = await sym.close_position()

            print("orphan closing response , kucoin me ", res)

            await private_manager.kucoin.remove_symbol(symbol)

    except Exception as e:
        print("Recovery orphan close failed:", e)


# ---------------------------------------------------------
# MAIN RECOVERY
# ---------------------------------------------------------

async def run_startup_recovery(private_manager, live_data_dict):

    print("🔄 STARTUP RECOVERY START")

    positions = await private_manager.fetch_positions()

    bybit_positions = positions.get("bybit", [])
    kucoin_positions = positions.get("kucoin", [])

    print("inside run startup recovery, first print , both positions:",positions)

    grouped = {}

    # -------------------------------------------------
    # GROUP BY NORMALIZED SYMBOL
    # -------------------------------------------------

    for p in bybit_positions:
        norm = normalize_futures_symbol(p["symbol"])
        grouped.setdefault(norm, {})
        p["exchange"] = "bybit"
        grouped[norm]["bybit"] = p

    for p in kucoin_positions:
        norm = normalize_futures_symbol(p["symbol"])
        grouped.setdefault(norm, {})
        p["exchange"] = "kucoin"
        grouped[norm]["kucoin"] = p

    # -------------------------------------------------
    # PROCESS EACH SYMBOL
    # -------------------------------------------------

    for symbol, legs in grouped.items():

        bybit_pos = legs.get("bybit")
        kucoin_pos = legs.get("kucoin")

        print("bybit position :",bybit_pos, "kucoin position: ",kucoin_pos)

        # ---------------------------------------------
        # ORPHAN CASE
        # ---------------------------------------------

        if not bybit_pos or not kucoin_pos:

            orphan = bybit_pos if bybit_pos else kucoin_pos
            print("⚠️ Orphan position detected:", orphan["symbol"],"full:",orphan)

            await close_orphan_position(private_manager, orphan)
            continue

        # ---------------------------------------------
        # REST HEDGE CHECK
        # ---------------------------------------------

        if not rest_hedge_check(bybit_pos, kucoin_pos):

            print("❌ REST hedge mismatch – closing:", symbol)

            await close_orphan_position(private_manager, bybit_pos)
            await close_orphan_position(private_manager, kucoin_pos)
            continue

        # ---------------------------------------------
        # WAIT LIVE DATA
        # ---------------------------------------------

        await wait_for_live_data(symbol, live_data_dict)

        tolerance = 0.003

        print("after live data fill check !")

        if not live_data_hedge_check(symbol, bybit_pos, kucoin_pos, live_data_dict, tolerance):

            print("❌ LIVE hedge mismatch – closing:", symbol)

            await close_orphan_position(private_manager, bybit_pos)
            await close_orphan_position(private_manager, kucoin_pos)
            continue

        # ---------------------------------------------
        # CREATE SYMBOL ENGINES
        # ---------------------------------------------

        data = live_data_dict[symbol]

        bb_real = data["bybit"]["original_name"]["value"]
        ku_real = data["kucoin"]["original_name"]["value"]

        sym_bybit = await private_manager.bybit.add_symbol(bb_real)
        sym_kucoin = await private_manager.kucoin.add_symbol(ku_real)

        mult_b = float(data["bybit"]["multiplier"]["value"])
        mult_k = float(data["kucoin"]["multiplier"]["value"])

        qty_b = float(bybit_pos["size"])
        qty_k = float(kucoin_pos["size"])

        base_b = qty_b * mult_b
        base_k = qty_k * mult_k

        base_exposure = max(base_b , base_k)

        bb_price = float(bybit_pos["entry_price"])
        ku_price = float(kucoin_pos["entry_price"])

        notional_b = base_exposure * bb_price
        notional_k = base_exposure * ku_price

        long_exchange = "bybit" if bybit_pos["side"] == "long" else "kucoin"
        short_exchange = "kucoin" if long_exchange == "bybit" else "bybit"

        sym_long = sym_bybit if long_exchange == "bybit" else sym_kucoin
        sym_short = sym_kucoin if short_exchange == "kucoin" else sym_bybit

        trade_id = uuid.uuid4().hex

        # ---------------------------------------------
        # BUILD LEGS
        # ---------------------------------------------

        long_leg = {
            "exchange": long_exchange,
            "engine": sym_long,
            "side": "buy",
            "qty": qty_b if long_exchange == "bybit" else qty_k,
            "multiplier": mult_b if long_exchange == "bybit" else mult_k,
            "notional": notional_b if long_exchange == "bybit" else notional_k,
            "entry_price": bb_price if long_exchange == "bybit" else ku_price
        }

        short_leg = {
            "exchange": short_exchange,
            "engine": sym_short,
            "side": "sell",
            "qty": qty_k if short_exchange == "kucoin" else qty_b,
            "multiplier": mult_k if short_exchange == "kucoin" else mult_b,
            "notional": notional_k if short_exchange == "kucoin" else notional_b,
            "entry_price": ku_price if short_exchange == "kucoin" else bb_price
        }

        
        # -----------------------------
        # HYDRATE BYBIT STATE
        # -----------------------------

        sym_bybit.state["position"] = bybit_pos["full_response_dict"]
        sym_bybit.state["side"] = bybit_pos["side"]
        sym_bybit.state["size"] = bybit_pos["size"]
        sym_bybit.state["entry_price"] = bybit_pos["entry_price"]
        sym_bybit.state["liquidation_price"] = bybit_pos["full_response_dict"].get("liqPrice")
        sym_bybit.state["unrealized_pnl"] = float(bybit_pos["full_response_dict"].get("unrealisedPnl",0))


        # -----------------------------
        # HYDRATE KUCOIN STATE
        # -----------------------------

        k = kucoin_pos["full_response_dict"]

        sym_kucoin.state["position"] = k
        sym_kucoin.state["side"] = kucoin_pos["side"]
        sym_kucoin.state["size"] = kucoin_pos["size"]
        sym_kucoin.state["entry_price"] = kucoin_pos["entry_price"]
        sym_kucoin.state["liquidation_price"] = k.get("liquidationPrice")
        sym_kucoin.state["unrealized_pnl"] = float(k.get("unrealisedPnl",0))

        # ---------------------------------------------
        # LOGGER (same as entry flow)
        # ---------------------------------------------

        logger = TradeLogger(symbol)
        logger.log_event("recovery_trade_detected")

        # ---------------------------------------------
        # CREATE TRADE CONTEXT
        # ---------------------------------------------


        trade = TradeContext(
            symbol_name=symbol,
            long_engine=sym_long,
            short_engine=sym_short,
            long_exchange=long_exchange,
            short_exchange=short_exchange,
            bb_qty=qty_b,
            ku_qty=qty_k,
            bb_notional=notional_b,
            ku_notional=notional_k,
            entry_price_long=long_leg["entry_price"],
            entry_price_short=short_leg["entry_price"],
            long_leg=long_leg,
            short_leg=short_leg,
            entry_dominant_exchange=None,
            entry_funding_sign=0,
            bb_funding=0,
            ku_funding=0,
            entry_funding_difference=0,
            mult_b=mult_b,
            mult_k=mult_k,
            base_exposure=base_exposure,
            trade_id=trade_id,
            entry_div_percent=0
        )

        trade.logger = logger
        logger.log_event("trade_context_created")

        # ---------------------------------------------
        # TRADE REGISTRY
        # ---------------------------------------------

        if len(TRADE_REGISTRY) >= MAX_REGISTRY_HISTORY:
            oldest_key = next(iter(TRADE_REGISTRY))
            TRADE_REGISTRY.pop(oldest_key, None)

        TRADE_REGISTRY[trade_id] = {
            "trade_id": trade_id,
            "symbol": symbol,
            "status": "RECOVERED",
            "created_at": time.time(),
            "engines": {
                "long": sym_long,
                "short": sym_short,
                "long_exchange": long_exchange,
                "short_exchange": short_exchange
            },
            "trade_object": trade
        }

        ACTIVE_TRADES[symbol] = trade

        # ---------------------------------------------
        # START MONITOR
        # ---------------------------------------------

        task = asyncio.create_task(
            monitor_trade(
                trade,
                private_manager,
                live_data_dict
            )
        )

        trade.monitor_task = task

        logger.log_event("recovery_trade_activated")

        print("✅ Recovered trade:", symbol)

    print("✅ STARTUP RECOVERY COMPLETE")