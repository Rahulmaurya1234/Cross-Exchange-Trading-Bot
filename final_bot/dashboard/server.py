# dashboard/server.py
import asyncio
import time
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
from strategy.control import global_kill
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
# try to import the central public feed (preferred)
try:
    from public.centre import SORTED_TOP,LIVE_DATA_DICT
except Exception:
    LIVE_DATA_DICT = None

from strategy.globals import (
    ACTIVE_TRADES,
    CLOSED_TRADES,
    ENTRY_CONTROL,
    TRADE_REGISTRY,
    RUNTIME_CONFIG
)


app = FastAPI()
private_manager_ref = None


# ------------------ small helpers ------------------
def _safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _get_from_dict(d, *keys, default=None):
    try:
        x = d
        for k in keys:
            if x is None:
                return default
            x = x.get(k)
        return x if x is not None else default
    except Exception:
        return default


def _calculate_divergence(public_data):
    try:
        mb = _safe_float(_get_from_dict(public_data, "bybit", "mark_price", "value"))
        mk = _safe_float(_get_from_dict(public_data, "kucoin", "mark_price", "value"))
        if not mb or not mk or mb <= 0 or mk <= 0:
            return None
        ref = (mb + mk) / 2.0
        return abs(mb - mk) / ref
    except Exception:
        return None


def _liquidation_distance(state):
    try:
        mark = _safe_float(state.get("mark_price"))
        liq = _safe_float(state.get("liquidation_price"))
        side = (state.get("side") or "").lower()
        if not mark or not liq:
            return None
        if side == "long":
            return (mark - liq) / mark
        if side == "short":
            return (liq - mark) / mark
    except Exception:
        return None
    return None


def _current_notional(state):
    try:
        size = abs(_safe_float(state.get("size") or 0))
        mark = _safe_float(state.get("mark_price"))
        if not size or not mark:
            return None
        return size * mark
    except Exception:
        return None


# ------------------ builders ------------------


def _build_leg_snapshot(leg, state, trade):
    entry_price = leg.get("entry_price")
    entry_notional = leg.get("notional")
    multiplier = leg.get("multiplier")

    mark_price = _safe_float(state.get("mark_price"))
    unrealized = _safe_float(state.get("unrealized_pnl")) or 0.0
    liq_price = _safe_float(state.get("liquidation_price"))
    size = _safe_float(state.get("size"))

    current_notional = None
    if size and mark_price:
        current_notional = abs(size) * mark_price

    pnl_percent = None
    if current_notional and current_notional != 0:
        pnl_percent = unrealized / current_notional

    price_change = None
    if entry_price and mark_price:
        price_change = (mark_price - entry_price) / entry_price

    if leg.get("side") == "short":
        price_change = -price_change

    liq_buffer = _liquidation_distance(state)

    base_exposure = None
    if size and multiplier:
        base_exposure = abs(size) * multiplier

    return {
        "exchange": leg["exchange"],
        "static": {
            "entry_price": entry_price,
            "entry_notional": entry_notional,
            "multiplier": multiplier,
        },
        "dynamic": {
            "mark_price": mark_price,
            "size": size,
            "unrealized_pnl": unrealized,
            "liquidation_price": liq_price
        },
        "derived": {
            "current_notional": current_notional,
            "base_exposure": base_exposure,
            "pnl_percent": pnl_percent,
            "price_change_percent": price_change,
            "liquidation_buffer_percent": liq_buffer
        }
    }


def _build_combined_snapshot(trade, public_data, long_state, short_state, long_snapshot, short_snapshot):
    long_upnl = _safe_float(long_state.get("unrealized_pnl")) or 0
    short_upnl = _safe_float(short_state.get("unrealized_pnl")) or 0

    long_size = abs(_safe_float(long_state.get("size")) or 0)
    short_size = abs(_safe_float(short_state.get("size")) or 0)

    exposure_long = long_snapshot["derived"]["base_exposure"] or 0
    exposure_short = short_snapshot["derived"]["base_exposure"] or 0

    exposure_drift = exposure_long - exposure_short

    funding_diff = None
    try:
        f_b = _safe_float(_get_from_dict(public_data, "bybit", "funding_rate_decimal", "value"))
        f_k = _safe_float(_get_from_dict(public_data, "kucoin", "funding_rate_decimal", "value"))
        if f_b is not None and f_k is not None:
            funding_diff = abs(f_b - f_k)
    except:
        funding_diff = None

    divergence = _calculate_divergence(public_data)

    dominant_side = None
    if trade.long_leg["exchange"] == trade.entry_dominant_exchange:
        dominant_side = "long"
    elif trade.short_leg["exchange"] == trade.entry_dominant_exchange:
        dominant_side = "short"

    return {
        "static": {
            "entry_funding_difference": getattr(trade, "entry_funding_difference", None),
            "entry_divergence_percent": getattr(trade, "entry_div_percent", None),
            "dominant_exchange": trade.entry_dominant_exchange,
            "dominant_side": dominant_side
        },
        "dynamic": {
            "funding_difference": funding_diff,
            "current_divergence_percent": divergence,
            "total_unrealized_pnl": long_upnl + short_upnl,
            "exposure_drift_base": exposure_drift,
            "pnl_difference": long_upnl - short_upnl
        },
        "risk": {
            "divergence_limit": RUNTIME_CONFIG.max_divergence_exit,
            "divergence_breached": (divergence is not None and divergence > RUNTIME_CONFIG.max_divergence_exit),
            "liq_buffer_limit": RUNTIME_CONFIG.min_liq_buffer,
            "exposure_tolerance": trade.base_exposure * 0.0001 if getattr(trade, "base_exposure", None) is not None else None,
            "exposure_mismatch": (abs(exposure_drift) > (trade.base_exposure * 0.0001 if getattr(trade, "base_exposure", None) is not None else 0))
        }
    }


# ------------------ root snapshot ------------------
def build_snapshot():
    now = time.time()

    balances = {}
    if private_manager_ref:
        try:
            balances["bybit"] = private_manager_ref.bybit.get_account_state()
            balances["kucoin"] = private_manager_ref.kucoin.get_account_state()
        except:
            balances = {}

    active_trades = []
    for symbol, trade in list(ACTIVE_TRADES.items()):
        # public_data can be available inside engines or central dict: try to find best
                # --- Public data resolution for ACTIVE TRADES (STRICT) ---
        public_data = None

        # 1) Prefer central LIVE_DATA_DICT (the public feed you maintain)
        try:
            if LIVE_DATA_DICT:
                public_data = LIVE_DATA_DICT.get(symbol)
        except Exception:
            public_data = None

        # 2) Defensive: ask the symbol engine if it can provide public snapshot
        #    (some engine implementations may expose a helper method)
        if public_data is None:
            for attr in ("get_public_data", "get_latest_public", "public_data"):
                try:
                    fn = getattr(trade.long_engine, attr, None)
                    if callable(fn):
                        # try call; many engine methods may accept symbol or not —
                        # call defensively with no args first, then with symbol
                        try:
                            cand = fn()
                        except TypeError:
                            try:
                                cand = fn(symbol)
                            except Exception:
                                cand = None
                        if cand:
                            public_data = cand
                            break
                except Exception:
                    continue

        # 3) DO NOT use SORTED_TOP for active trade math — only a display fallback (so skip here)
        if public_data is None:
            # cannot build reliable combined metrics without public data — skip this trade for snapshot
            # (this preserves correctness: frontend simply won't show the card until public data arrives)
            continue

        long_state = trade.long_engine.get_state()
        short_state = trade.short_engine.get_state()

        long_leg_snapshot = _build_leg_snapshot(
            trade.long_leg,
            long_state,
            trade
        )

        short_leg_snapshot = _build_leg_snapshot(
            trade.short_leg,
            short_state,
            trade
        )

        active_trades.append({
            "symbol": symbol,
            "status": trade.status,
            "created_at": trade.created_at,
            "trade_id": getattr(trade, "trade_id", None),
            "exchange_long": long_leg_snapshot,
            "exchange_short": short_leg_snapshot,
            "combined": _build_combined_snapshot(trade, public_data, long_state, short_state, long_leg_snapshot, short_leg_snapshot)
        })

    # closed trades (enhanced)
    closed = []
    for trade in CLOSED_TRADES:
        closed.append({
            "symbol": trade.symbol,
            "trade_id": getattr(trade, "trade_id", None),
            "created_at": trade.created_at,
            "closed_at": trade.closed_at,
            "realized_pnl": getattr(trade, "realized_pnl", None),
            "total_fees": getattr(trade, "total_fees", None),
            "entry_funding_difference": getattr(trade, "entry_funding_difference", None),
            "entry_divergence_percent": getattr(trade, "entry_div_percent", None),
            "exit_reason": getattr(trade, "exit_reason", None)
        })

    # ---------- opportunities (DISPLAY ONLY) ----------
    sorted_view = []
    for symbol, data in SORTED_TOP.items():
        try:
            # prefer fields from SORTED_TOP, fall back to nested public-like fields
            funding_diff = _safe_float(_get_from_dict(data, "funding_rate_difference_decimal", "value")) \
                or _safe_float(_get_from_dict(data, "funding_rate_difference_decimal"))

            # additional public display fields (best-effort)
            bb_funding = _safe_float(_get_from_dict(data, "bybit", "funding_rate_decimal", "value")) \
                or _safe_float(_get_from_dict(data, "bybit", "funding_rate_decimal"))
            ku_funding = _safe_float(_get_from_dict(data, "kucoin", "funding_rate_decimal", "value")) \
                or _safe_float(_get_from_dict(data, "kucoin", "funding_rate_decimal"))

            bb_mark = _safe_float(_get_from_dict(data, "bybit", "mark_price", "value"))
            ku_mark = _safe_float(_get_from_dict(data, "kucoin", "mark_price", "value"))

            bb_bid = _safe_float(_get_from_dict(data, "bybit", "best_bid_price", "value"))
            bb_ask = _safe_float(_get_from_dict(data, "bybit", "best_ask_price", "value"))
            ku_bid = _safe_float(_get_from_dict(data, "kucoin", "best_bid_price", "value"))
            ku_ask = _safe_float(_get_from_dict(data, "kucoin", "best_ask_price", "value"))

            bb_min_qty = _safe_float(_get_from_dict(data, "bybit", "min_order_qty", "value"))
            ku_min_qty = _safe_float(_get_from_dict(data, "kucoin", "min_order_qty", "value"))

            bb_mult = _safe_float(_get_from_dict(data, "bybit", "multiplier", "value"))
            ku_mult = _safe_float(_get_from_dict(data, "kucoin", "multiplier", "value"))

            bb_fee_maker = _safe_float(_get_from_dict(data, "bybit", "maker_fee", "value")) or _safe_float(_get_from_dict(data, "bybit", "maker_fee"))
            bb_fee_taker = _safe_float(_get_from_dict(data, "bybit", "taker_fee", "value")) or _safe_float(_get_from_dict(data, "bybit", "taker_fee"))
            ku_fee_maker = _safe_float(_get_from_dict(data, "kucoin", "maker_fee", "value")) or _safe_float(_get_from_dict(data, "kucoin", "maker_fee"))
            ku_fee_taker = _safe_float(_get_from_dict(data, "kucoin", "taker_fee", "value")) or _safe_float(_get_from_dict(data, "kucoin", "taker_fee"))

            ku_next = _safe_float(_get_from_dict(data, "kucoin", "next_funding_at_utc", "value"))
            bb_next = _safe_float(_get_from_dict(data, "bybit", "next_funding_at_utc", "value"))
            earliest_funding = None
            if ku_next and bb_next:
                earliest_funding = min(ku_next, bb_next)
            elif ku_next:
                earliest_funding = ku_next
            elif bb_next:
                earliest_funding = bb_next

            time_to_funding = None
            if earliest_funding:
                try:
                    time_to_funding = max(0, int(earliest_funding - time.time()))
                except:
                    time_to_funding = None

                        # compute freshness: prefer kucoin's best_bid timestamp, else bybit's
            freshness = None
            try:
                ts_ku = _get_from_dict(data, "kucoin", "best_bid_price", "ts")
                ts_bb = _get_from_dict(data, "bybit", "best_bid_price", "ts")
                ts = None
                if ts_ku:
                    ts = float(ts_ku)
                elif ts_bb:
                    ts = float(ts_bb)
                if ts:
                    freshness = int(max(0, time.time() - ts))
            except Exception:
                freshness = None

            # then in the dict include:
            

            sorted_view.append({
                "symbol": symbol,
                "funding_diff": funding_diff,
                "interval": _safe_float(_get_from_dict(data, "kucoin", "funding_interval_hr", "value")) or _safe_float(_get_from_dict(data, "kucoin", "funding_interval_hr")),
                "ku_funding": ku_funding,
                "bb_funding": bb_funding,
                "ku_mark": ku_mark,
                "bb_mark": bb_mark,
                "ku_bid": ku_bid,
                "ku_ask": ku_ask,
                "bb_bid": bb_bid,
                "bb_ask": bb_ask,
                "ku_min_qty": ku_min_qty,
                "bb_min_qty": bb_min_qty,
                "ku_mult": ku_mult,
                "bb_mult": bb_mult,
                "ku_fee_maker": ku_fee_maker,
                "ku_fee_taker": ku_fee_taker,
                "bb_fee_maker": bb_fee_maker,
                "bb_fee_taker": bb_fee_taker,
                "time_to_funding": time_to_funding,
                "freshness": freshness
            })
        except Exception:
            # skip faulty entries
            continue

        # -------- METRICS (for frontend quick display) --------
    total_edge = sum(item.get("funding_diff", 0) or 0 for item in sorted_view)
    avg_interval = (
        sum(item.get("interval", 0) for item in sorted_view if item.get("interval"))
        / len([item for item in sorted_view if item.get("interval")])
        if sorted_view else 0
    )

    return {
        "timestamp": now,
        "entry_allowed": ENTRY_CONTROL.allowed,
        "balances": balances,
        "active_trades": active_trades,
        "closed_trades": closed,
        "opportunities": sorted_view,
        "metrics": {
            "total_edge": total_edge,
            "avg_interval": avg_interval
        },
        "runtime_config": {
            "max_active_trades": RUNTIME_CONFIG.max_active_trades,
            "cooldown_seconds": RUNTIME_CONFIG.cooldown_seconds,
            "max_divergence_exit": RUNTIME_CONFIG.max_divergence_exit,
            "min_liq_buffer": RUNTIME_CONFIG.min_liq_buffer,
            "min_funding_diff": RUNTIME_CONFIG.min_funding_diff,
            "leverage": RUNTIME_CONFIG.leverage,
            "max_margin_usage_percent": RUNTIME_CONFIG.max_margin_usage_percent,
            "time_remained_to_fund": RUNTIME_CONFIG.time_remained_to_fund
        }
    }


# ------------------ HTTP / WS Endpoints ------------------
class EntryToggleRequest(BaseModel):
    allowed: bool


class RuntimeConfigUpdate(BaseModel):
    max_active_trades: int | None = None
    cooldown_seconds: int | None = None
    time_remained_to_fund: int | None = None
    max_divergence_exit: float | None = None
    min_liq_buffer: float | None = None
    min_funding_diff: float | None = None
    leverage: int | None = None
    max_margin_usage_percent: float | None = None


@app.post("/kill-all")
async def kill_all():
    print("🔥 /kill-all endpoint hit")

    if not private_manager_ref:
        return {"status": "error", "reason": "private_manager_not_ready"}

    try:
        await global_kill(private_manager_ref)
        return {"status": "kill_executed"}
    except Exception as e:
        print("KILL ERROR:", repr(e))
        return {"status": "error", "reason": str(e)}

@app.get("/")
async def root():
    path = os.path.join(TEMPLATE_DIR, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/settings")
async def settings():
    path = os.path.join(TEMPLATE_DIR, "settings.html")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/toggle-entry")
async def toggle_entry(req: EntryToggleRequest):
    ENTRY_CONTROL.allowed = req.allowed
    return {"entry_allowed": ENTRY_CONTROL.allowed}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "live_data_available": bool(LIVE_DATA_DICT),
        "active_trades_count": len(ACTIVE_TRADES),
        "closed_trades_count": len(CLOSED_TRADES),
        "entry_allowed": ENTRY_CONTROL.allowed,
        "timestamp": time.time()
    }

@app.post("/update-runtime")
async def update_runtime(req: RuntimeConfigUpdate):
    # update only when provided
    if req.max_active_trades is not None:
        RUNTIME_CONFIG.max_active_trades = req.max_active_trades
    if req.cooldown_seconds is not None:
        RUNTIME_CONFIG.cooldown_seconds = req.cooldown_seconds
    if req.max_divergence_exit is not None:
        RUNTIME_CONFIG.max_divergence_exit = req.max_divergence_exit
    if req.min_funding_diff is not None:
        RUNTIME_CONFIG.min_funding_diff = req.min_funding_diff
    if req.time_remained_to_fund is not None:
        RUNTIME_CONFIG.time_remained_to_fund = req.time_remained_to_fund
    if req.min_liq_buffer is not None:
        RUNTIME_CONFIG.min_liq_buffer = req.min_liq_buffer
    if req.leverage is not None:
        RUNTIME_CONFIG.leverage = req.leverage
    if req.max_margin_usage_percent is not None:
        if 0 < req.max_margin_usage_percent <= 1:
            RUNTIME_CONFIG.max_margin_usage_percent = req.max_margin_usage_percent

    return {"status": "runtime_updated"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(build_snapshot())
            await asyncio.sleep(1)
    except Exception as e:
        print("", repr(e), flush=True)

@app.websocket("/ws/public")
async def public_ws(websocket: WebSocket):

    await websocket.accept()

    try:
        while True:

            # send snapshot copy of public data
            await websocket.send_json(dict(LIVE_DATA_DICT or {}))

            await asyncio.sleep(0.5)

    except Exception as e:
        print("public websocket closed:", e)

async def start_dashboard(private_manager):
    global private_manager_ref
    private_manager_ref = private_manager

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="warning"
    )
    server = uvicorn.Server(config)
    await server.serve()