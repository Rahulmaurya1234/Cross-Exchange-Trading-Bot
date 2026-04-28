import re


MIN_24H_VOLUME_USD = 100_000


# ==========================================================
# UTILITIES
# ==========================================================

def normalize_futures_symbol(symbol: str) -> str:
    """
    Normalize symbol to common format:
    XBTUSDTM -> BTCUSDT
    BTC-USDT -> BTCUSDT
    """

    if not symbol:
        return ""

    clean = re.sub(r"[-_/]", "", symbol).upper()

    if clean.startswith("XBT"):
        clean = clean.replace("XBT", "BTC", 1)

    if clean.endswith("USDTM"):
        clean = clean[:-1]  # remove trailing M

    return clean


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ==========================================================
# CORE MATCHER
# ==========================================================

def matcher(bybit_ticker_raw, bybit_instrument_raw, kucoin_raw):

    matched_results = []

    if not isinstance(bybit_ticker_raw, list) or not isinstance(kucoin_raw, list) or not isinstance(bybit_instrument_raw,list):
        return []

    # --------------------------------------------------
    # 1️⃣ Preprocess Bybit
    # --------------------------------------------------

    bybit_ticker_map = {}
    bybit_instrument_map = {}

    for item in bybit_ticker_raw:
        try:
            symbol = item.get("symbol")
            norm = normalize_futures_symbol(symbol)

            if not norm.endswith("USDT"):
                continue

            bb_vol = safe_float(item.get("turnover24h"))
            if bb_vol is None or bb_vol < MIN_24H_VOLUME_USD:
                continue

            fund_hour = safe_float(item.get("fundingIntervalHour"))
            if fund_hour is None:
                continue

            funding_minutes = int(fund_hour) * 60

            bybit_ticker_map[norm] = {
                "raw": item,
                "funding_minutes": funding_minutes,
            }

        except Exception:
            continue
    
    for item in bybit_instrument_raw:
        try:
            if item.get("status") != "Trading":
                continue

            symbol = item.get("symbol")
            norm = normalize_futures_symbol(symbol)

            if not norm.endswith("USDT"):
                continue

            price_filter = item.get("priceFilter", {})
            lot_filter = item.get("lotSizeFilter", {})
            fee_info_filter = item.get("auctionFeeInfo",{})

            ticksize = safe_float(price_filter.get("tickSize"))
            lotsize = safe_float(lot_filter.get("qtyStep"))
            minorder = safe_float(lot_filter.get("minOrderQty"))
            takerfee = safe_float(fee_info_filter.get("takerFeeRate"))
            makerfee = safe_float(fee_info_filter.get("makerFeeRate"))

            bybit_instrument_map[norm] = {
                "tick_size": ticksize,
                "lot_size": lotsize,
                "min_qty": minorder,
                "maker_fee":makerfee,
                "taker_fee":takerfee,
            }

        except Exception:
            continue




    # --------------------------------------------------
    # 2️⃣ Match with Kucoin
    # --------------------------------------------------

    for ku_item in kucoin_raw:
        try:
            ku_symbol = ku_item.get("symbol")
            norm = normalize_futures_symbol(ku_symbol)

            if norm not in bybit_ticker_map:
                continue
            
            if norm not in bybit_instrument_map:
                continue

            ku_vol = safe_float(ku_item.get("turnoverOf24h"))
            if ku_vol is None or ku_vol < MIN_24H_VOLUME_USD:
                continue

            granularity = safe_float(ku_item.get("fundingRateGranularity"))
            if granularity is None:
                continue

            ku_funding_minutes = int(granularity) // 60000

            bb_instr = bybit_instrument_map[norm]
            bb_ticker = bybit_ticker_map[norm]

            # STRICT: funding interval must match exactly
            if bb_ticker["funding_minutes"] != ku_funding_minutes:
                continue

            bb_item = bb_ticker["raw"]

            # -------------------------
            # Strict field extraction
            # -------------------------

            bb_next = safe_float(bb_item.get("nextFundingTime"))
            ku_next = safe_float(ku_item.get("nextFundingRateDateTime"))

            ku_tick = safe_float(ku_item.get("tickSize"))
            ku_lot = safe_float(ku_item.get("lotSize"))
            ku_multiplier = safe_float(ku_item.get("multiplier"))
            matched_results.append({

                # COMMON NORMALIZED SYMBOL
                "symbol": norm,

                # ORIGINAL EXCHANGE NAMES
                "bb_name": bb_item.get("symbol"),
                "original_name": ku_symbol,  # renamed from ku_name
                "bb_funding_rate":safe_float(bb_item.get("fundingRate")),
                # FUNDING TIMES (UTC seconds)
                "bb_next_funding_time": bb_next / 1000 if bb_next else None,
                "ku_next_funding_time": ku_next / 1000 if ku_next else None,

                # Funding interval consistency
                "funding_interval_hours": bb_ticker["funding_minutes"] // 60,
                #bybit trading parameters 
                "ku_funding_rate": safe_float(ku_item.get("fundingFeeRate")),
                "bb_tick_size": bb_instr["tick_size"],
                "bb_lot_size" : bb_instr["lot_size"],
                "bb_min_order_qty" : bb_instr["min_qty"],
                # Kucoin trading parameters
                "ku_tick_size": ku_tick,
                "ku_lot_size": ku_lot,
                "ku_min_order_qty": ku_lot,
                "ku_multiplier":ku_multiplier,
                #feerates
                "ku_maker_fee_rate": safe_float(ku_item.get("makerFeeRate")),
                "ku_taker_fee_rate":safe_float(ku_item.get("takerFeeRate")),
                "bb_maker_fee_rate": safe_float(bb_instr.get("maker_fee")),
                "bb_taker_fee_rate" : safe_float(bb_instr.get("taker_fee"))
            })

        except Exception:
            continue

    return matched_results
