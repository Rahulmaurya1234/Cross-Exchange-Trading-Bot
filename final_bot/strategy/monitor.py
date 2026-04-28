import asyncio
import time
import copy
from config import MONITOR_INTERVAL
from strategy.globals import (
    ACTIVE_TRADES,
    COOLDOWN,
    CLOSED_TRADES,
    MAX_CLOSED_HISTORY,
    TRADE_REGISTRY,
    RUNTIME_CONFIG,
)


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


def liquidation_distance(state):
    try:
        # guard against None or missing keys
        mark_price = state.get("mark_price")
        liq_price = state.get("liquidation_price")
        if mark_price is None or liq_price is None:
            return None
        mark_price = float(mark_price)
        liq_price = float(liq_price)
        side = (state.get("side") or "").lower()
    except Exception:
        return None

    # explicit None / zero checks
    if mark_price <= 0 or liq_price <= 0:
        return None

    if side == "long":
        distance = (mark_price - liq_price) / mark_price
    elif side == "short":
        distance = (liq_price - mark_price) / mark_price
    else:
        return None

    return distance


def _extract_notional_from_state(trade, state, leg):
    """
    Return notional (positive float) using priority:
      1) leg[notional]
      2) state['position'] common fields like positionValue, markValue, posCost, currentCost, filledValue
      3) abs(size * mark_price) fallback
      4) None if not derivable
    `is_long` True => prefer trade.bb_notional, else trade.ku_notional
    """

    
        # 1) trade-level notional if present
    try:
        val = leg["notional"]
        if val is not None:
            return abs(float(val))
    except Exception:
        pass

    # 2) try common position fields in state['position']
    try:
        print("inside extract notionla second try")
        pos = state.get("position") or {}
        for key in ("positionValue", "markValue", "posCost", "currentCost", "filledValue", "filled_value", "position_value", "mark_value"):
            if key in pos and pos[key] is not None:
                try:
                    return abs(float(pos[key]))
                except Exception:
                    continue
    except Exception:
        pass

    # 3) fallback compute: abs(size * mark_price)
    try:
        print("inside extract notionla third try")
        size = state.get("size") or 0
        mark = state.get("mark_price") or 0
        size_f = float(size or 0)
        mark_f = float(mark or 0)
        if size_f != 0 and mark_f != 0:
            return abs(size_f * mark_f)
    except Exception:
        pass

    # 4) give up
    return None

def funding_flipped(trade, public_data):
    """
    Defensive funding check.
    Returns tuple: (flipped: bool, meta: dict)
    meta contains debug info that can be logged.
    """

    meta = {}
    try:
        ku_funding = float(public_data["kucoin"]["funding_rate_decimal"]["value"])
    except Exception as e:
        ku_funding = None
        meta["ku_error"] = str(e)
    try:
        bb_funding = float(public_data["bybit"]["funding_rate_decimal"]["value"])
    except Exception as e:
        bb_funding = None
        meta["bb_error"] = str(e)

    # select which exchange to examine for this trade
    if trade.entry_dominant_exchange == "kucoin":
        current = ku_funding
        next_funding_time = public_data.get("kucoin", {}).get("next_funding_at_utc", {}).get("value")
        exchange = "kucoin"
    else:
        current = bb_funding
        next_funding_time = public_data.get("bybit", {}).get("next_funding_at_utc", {}).get("value")
        exchange = "bybit"

    meta.update({"exchange": exchange, "ku_funding": ku_funding, "bb_funding": bb_funding, "entry_sign": trade.entry_funding_sign})

    if current is None:
        meta["reason"] = "missing_current_funding"
        return False, meta

    if current > 0:
        current_sign = 1
    elif current < 0:
        current_sign = -1
    else:
        meta["reason"] = "funding_zero"
        meta["current"] = current
        return False, meta

    meta["current_sign"] = current_sign
    # Defensive next_funding_time parsing
    try:
        next_funding_time = float(next_funding_time)
        meta["next_funding_time"] = next_funding_time
    except Exception as e:
        meta["next_funding_time_error"] = str(e)
        return False, meta

    time_to_funding = next_funding_time - time.time()
    meta["time_to_funding"] = time_to_funding

    # Use your suggested threshold (avoid immediately negative stale values)
    # Only consider flip if sign changed AND funding is imminent but not stale-negative
    if current_sign != trade.entry_funding_sign and (0.1 < time_to_funding <= 300):
        meta["reason"] = "funding_flip"
        return True, meta

    meta["reason"] = "no_flip"
    return False, meta


def should_exit(trade, public_data, long_state, short_state):
    """
    Returns (bool, meta) so caller can log exact reason.
    Keep major logic same but be defensive on None/falsy checks.
    """

    meta = {}

    # 1️⃣ Exchange offline
    try:
        if public_data.get("bybit", {}).get("offline", {}).get("value"):
            return True, {"reason": "bybit_offline"}
        if public_data.get("kucoin", {}).get("offline", {}).get("value"):
            return True, {"reason": "kucoin_offline"}
    except Exception:
        # if offline flags missing, don't fail here; continue
        pass
    
    # print("should exit me symbol offline nhi hae")
    # 2️⃣ Divergence
    divergence = calculate_divergence(public_data)
    if divergence is not None and divergence > RUNTIME_CONFIG.max_divergence_exit:
        return True, {"reason": "divergence", "divergence": divergence}

    # print("divergence nikal rha hae ",divergence)

    # 2.5 funding flip (instrumented)
    flipped, flip_meta = funding_flipped(trade, public_data)
    if flipped:
        flip_meta["reason"] = "funding_flip"
        return True, flip_meta

    # 3️⃣ Position integrity
    try:
        long_qty = abs(float(long_state.get("size", 0) or 0))
        short_qty = abs(float(short_state.get("size", 0) or 0))
    except Exception as e:
        return True, {"reason": "parse_size_error", "exc": str(e)}

    if long_qty == 0 or short_qty == 0:
        return True, {"reason": "zero_size", "long_qty": long_qty, "short_qty": short_qty}

    # print("trade.long exchange",type(trade.long_exchange), trade.long_exchange)

    try:
        long_base = long_qty * trade.long_leg["multiplier"]
        short_base = short_qty * trade.short_leg["multiplier"]
        tol = getattr(trade, "base_exposure", 0) * 0.0001
    except Exception as e:
        return True, {"reason": "exposure_calc_error", "exc": str(e)}

    if abs(long_base - short_base) > tol:
        return True, {"reason": "exposure_mismatch", "long_base": long_base, "short_base": short_base, "tol": tol}

    # 4️⃣ Liquidation buffer
    long_dist = liquidation_distance(long_state)
    short_dist = liquidation_distance(short_state)

    if long_dist is not None and long_dist < RUNTIME_CONFIG.min_liq_buffer:
        return True, {"reason": "liquidation_risk_long", "long_dist": long_dist}
    if short_dist is not None and short_dist < RUNTIME_CONFIG.min_liq_buffer:
        return True, {"reason": "liquidation_risk_short", "short_dist": short_dist}

    # print("should exit bahar jaa rhe hae")
    return False, {"reason": "none"}


async def _attempt_close_with_retries(engine, max_retries=2, base_backoff=0.5):
    """
    Attempts to call engine.close_position up to (1 + max_retries) times.
    Returns the last response (or successful response).
    Respects that close_market is safe to send even if no position exists.
    """
    last_resp = None
    for attempt in range(max_retries + 1):
        try:
            resp = await engine.close_position()
            last_resp = resp
            # if success True, or response indicates "No open position" treat as terminal
            if isinstance(resp, dict) and resp.get("success") is True:
                return resp
            if isinstance(resp, dict) and resp.get("success") is False and resp.get("error") == "No open position":
                # Acceptable terminal state
                return resp
            # otherwise, will retry
        except Exception as e:
            # record exception and retry
            last_resp = {"success": False, "error": "exception", "exc": str(e)}
        # backoff before next try
        await asyncio.sleep(base_backoff * (attempt + 1))
    return last_resp


async def monitor_trade(trade, private_manager, live_data_dict):
    symbol = trade.symbol
    print(f"monitoring: {symbol}")
    try:
        logger = trade.logger
        logger.log_event("monitor_started")
        await asyncio.sleep(2)

        while trade.status == "ACTIVE":
            # print("monitoring chal ri hae ")
            public_data = live_data_dict.get(symbol)
            if not public_data:
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            long_state = trade.long_leg["engine"].get_state()
            short_state = trade.short_leg["engine"].get_state()

            # robust numeric zero check
            try:
                ls = float(long_state.get("size", 0) or 0)
                ss = float(short_state.get("size", 0) or 0)
            except Exception:
                ls, ss = None, None

            if abs(ls) < 1e-9 or abs(ss) < 1e-9:
                # log explicit detection (important)
                logger.log_event(
                    "zero_size_detected",
                    long_exchange = trade.long_leg["exchange"],
                    short_exchange = trade.short_leg["exchange"],
                    long_size=ls,
                    short_size=ss,
                    long_state=copy.deepcopy(long_state),
                    short_state=copy.deepcopy(short_state)
                )
                break
            
            # print("long and short size bhi hae ")
            try:
                long_upnl = float(long_state.get("unrealized_pnl", 0) or 0)
                short_upnl = float(short_state.get("unrealized_pnl", 0) or 0)
                trade.unrealized_pnl = long_upnl + short_upnl
            except Exception:
                trade.unrealized_pnl = 0.0

            exit_flag, reason_meta = should_exit(trade, public_data, long_state, short_state)
            if exit_flag:
                # **Single, rich log** when exit triggers — includes all important diagnostics
                # Avoid logging every loop; this is the detailed dump you wanted.
                # include funding info, entry_funding_sign, exposure, pnl, fees, states
                try:
                    # gather funding info defensively
                    ku_f = public_data.get("kucoin", {}).get("funding_rate_decimal", {}).get("value")
                    bb_f = public_data.get("bybit", {}).get("funding_rate_decimal", {}).get("value")
                    ku_next = public_data.get("kucoin", {}).get("next_funding_at_utc", {}).get("value")
                    bb_next = public_data.get("bybit", {}).get("next_funding_at_utc", {}).get("value")
                except Exception:
                    ku_f = bb_f = ku_next = bb_next = None

                # compute some notional / exposure info if available
                # compute some notional / exposure info using robust precedence:
                long_notional = _extract_notional_from_state(trade, long_state, trade.long_leg)
                short_notional = _extract_notional_from_state(trade, short_state, trade.short_leg)
                print("notional calculate ho gya ")
                # Add more metadata
                reason_meta_full = {
                    "exit_reason_meta": reason_meta,
                    "unrealized_pnl": trade.unrealized_pnl,
                    "realized_pnl": getattr(trade, "realized_pnl", None),
                    "total_fees": getattr(trade, "total_fees", 0),
                    "entry_funding_sign": getattr(trade, "entry_funding_sign", None),
                    "funding": {"kucoin": ku_f, "bybit": bb_f},
                    "next_funding_at_utc": {"kucoin": ku_next, "bybit": bb_next},
                    "time": time.time(),
                    "long_notional": long_notional,
                    "short_notional": short_notional,
                    "long_state": copy.deepcopy(long_state),
                    "short_state": copy.deepcopy(short_state),
                    "trade_attrs": {
                        "long_multiplier": trade.long_leg["multiplier"],
                        "short_multiplier": trade.short_leg["multiplier"],
                        "base_exposure": getattr(trade, "base_exposure", None),
                        "trade_id": getattr(trade, "trade_id", None),
                    },
                    "trade_context": {
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "long_exchange": trade.long_leg["exchange"],
                        "short_exchange": trade.short_leg["exchange"],
                        "entry_price_long": trade.entry_price_long,
                        "entry_price_short": trade.entry_price_short,
                    }
                }
                trade.exit_reason = reason_meta.get("reason")
                logger.log_event("exit_triggered", **reason_meta_full)
                print("Exit triggered:", symbol, reason_meta)  # simple console trace
                break
            # print("dusra loop chalne jaa rha hae ! ")
            await asyncio.sleep(MONITOR_INTERVAL)
    except asyncio.CancelledError:
        trade.status = "CLOSING"
        raise

    # ---------- begin close flow ----------
    trade.status = "CLOSING"
    logger.log_event("close_position_attempt")

    final_unrealized = trade.unrealized_pnl

    # Attempt concurrent closes, but with per-engine retries for robustness.
    try:
        logger.log_event("pre_close_state_snapshot",
            short_state=copy.deepcopy(short_state),
            long_state=copy.deepcopy(long_state),
            now=time.time()
        )
        # create tasks that perform retry logic per engine
        long_task = asyncio.create_task(_attempt_close_with_retries(trade.long_leg["engine"]))
        short_task = asyncio.create_task(_attempt_close_with_retries(trade.short_leg["engine"]))
        res_long = await long_task
        res_short = await short_task
    except Exception as e:
        logger.log_error("close_position_exception", str(e))
        res_long, res_short = None, None

    # log raw responses
    logger.log_event(
        "close_position_response",
        long_exchange = trade.long_leg["exchange"],
        short_exchange = trade.short_leg["exchange"],
        long_response=res_long,
        short_response=res_short
    )

    # If one side failed and returned not-success, attempt one additional targeted retry (safe call)
    # but avoid retrying if response indicates "No open position" which is acceptable.
    def needs_retry(resp):
        if resp is None:
            return True
        if isinstance(resp, dict):
            if resp.get("success") is True:
                return False
            # If explicit 'No open position' — no retry needed
            if resp.get("error") == "No open position":
                return False
            # Otherwise consider retry
            return True
        # unknown resp shape -> allow retry
        return True

    # targeted retries (one more attempt each side) with small backoff
    if needs_retry(res_long):
        try:
            await asyncio.sleep(0.5)
            res_long_retry = await _attempt_close_with_retries(trade.long_leg["engine"], max_retries=1, base_backoff=0.5)
            if res_long_retry:
                res_long = res_long_retry
                logger.log_event("close_position_long_retry", response=res_long)
        except Exception as e:
            logger.log_error("close_long_retry_exception", str(e))

    if needs_retry(res_short):
        try:
            await asyncio.sleep(0.5)
            res_short_retry = await _attempt_close_with_retries(trade.short_leg["engine"], max_retries=1, base_backoff=0.5)
            if res_short_retry:
                res_short = res_short_retry
                logger.log_event("close_position_short_retry", response=res_short)
        except Exception as e:
            logger.log_error("close_short_retry_exception", str(e))

    # compute fees safely
    try:
        long_fee = float(res_long.get("fee", 0)) if isinstance(res_long, dict) else 0
    except Exception:
        long_fee = 0
    try:
        short_fee = float(res_short.get("fee", 0)) if isinstance(res_short, dict) else 0
    except Exception:
        short_fee = 0
    trade.total_fees += long_fee + short_fee

    # prefer closed PnL reported by exchanges if present (safe extraction)
    def _extract_closed_pnl(resp):
        if not isinstance(resp, dict):
            return None
        # check common places
        if "closed_pnl" in resp:
            try:
                return float(resp["closed_pnl"])
            except Exception:
                pass
        # try raw nested
        raw = resp.get("raw") or resp.get("exchange_meta") or {}
        if isinstance(raw, dict):
            for key in ("closedPnl", "closed_pnl", "closed_pnl_usd", "closed_pnl_usd"):
                val = raw.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except Exception:
                        pass
        # sometimes exchange returns 'closedPnl' as string in top level
        if "closedPnl" in resp:
            try:
                return float(resp["closedPnl"])
            except Exception:
                pass
        return None

    long_closed_pnl = _extract_closed_pnl(res_long)
    short_closed_pnl = _extract_closed_pnl(res_short)

    if long_closed_pnl is not None or short_closed_pnl is not None:
        trade.realized_pnl = (long_closed_pnl or 0.0) + (short_closed_pnl or 0.0) - trade.total_fees
    else:
        # fallback to what we had (best-effort)
        trade.realized_pnl = final_unrealized - trade.total_fees

    trade.closed_at = time.time()

    logger.log_event("trade_closed", realized_pnl=trade.realized_pnl, total_fees=trade.total_fees)

    # defensive: refresh public_data before removing symbols
    public_data = live_data_dict.get(symbol) or {}
    bb_real_name = public_data.get("bybit", {}).get("original_name", {}).get("value")
    ku_real_name = public_data.get("kucoin", {}).get("original_name", {}).get("value")

    if bb_real_name:
        try:
            await private_manager.bybit.remove_symbol(bb_real_name)
        except Exception as e:
            logger.log_error("remove_symbol_bybit_failed", str(e))
    if ku_real_name:
        try:
            await private_manager.kucoin.remove_symbol(ku_real_name)
        except Exception as e:
            logger.log_error("remove_symbol_kucoin_failed", str(e))

    logger.close()

    print(
        f"Trade Closed → {trade.symbol} | "
        f"PnL: {trade.realized_pnl:.4f} | "
        f"Fees: {trade.total_fees:.4f}"
    )

    # update global state
    if symbol in ACTIVE_TRADES:
        ACTIVE_TRADES.pop(symbol, None)
        COOLDOWN[symbol] = time.time()

    # move trade to closed history
    CLOSED_TRADES.append(trade)

    # cap history
    if len(CLOSED_TRADES) > MAX_CLOSED_HISTORY:
        CLOSED_TRADES.pop(0)

    trade.status = "CLOSED"

    if hasattr(trade, "trade_id"):
        if trade.trade_id in TRADE_REGISTRY:
            TRADE_REGISTRY[trade.trade_id]["status"] = "CLOSED"
            TRADE_REGISTRY[trade.trade_id]["exit_reason"] = trade.exit_reason

    return