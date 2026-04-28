import time

BB_MAKER_FEE = 0.0002
BB_TAKER_FEE = 0.00055
BB_MULT = 1
def create_field():
    return {"value": None, "ts": None}


def ensure_symbol_structure(symbol, original_name, live_dict):

    if symbol not in live_dict:
        live_dict[symbol] = {}

    # =====================================================
    # KUCOIN SECTION
    # =====================================================

    if "kucoin" not in live_dict[symbol]:

        live_dict[symbol]["kucoin"] = {
            "offline": create_field(),
            "original_name": create_field(),

            "best_bid_price": create_field(),
            "best_bid_size": create_field(),
            "best_ask_price": create_field(),
            "best_ask_size": create_field(),

            "mark_price": create_field(),
            "index_price": create_field(),

            "funding_rate_decimal": create_field(),

            "next_funding_at_utc": create_field(),
            "funding_interval_hr": create_field(),

            "tick_size": create_field(),
            "lot_size": create_field(),
            "min_order_qty": create_field(),
            "multiplier": create_field(),

            "maker_fee": create_field(),
            "taker_fee": create_field(),
        }

    # =====================================================
    # BYBIT SECTION
    # =====================================================

    if "bybit" not in live_dict[symbol]:

        live_dict[symbol]["bybit"] = {
            "offline": create_field(),
            "original_name": create_field(),

            "best_bid_price": create_field(),
            "best_bid_size": create_field(),
            "best_ask_price": create_field(),
            "best_ask_size": create_field(),

            "mark_price": create_field(),
            "index_price": create_field(),

            "funding_rate_decimal": create_field(),

            "next_funding_at_utc": create_field(),
            "funding_interval_hr": create_field(),

            "tick_size": create_field(),
            "lot_size": create_field(),
            "min_order_qty": create_field(),
            "multiplier": create_field(),
            "maker_fee": create_field(),
            "taker_fee": create_field(),
        }


def dict_create_or_update(matched_list, live_dict):

    now = time.time()

    for item in matched_list:

        symbol = item["symbol"]
        original = item["original_name"]
        bb_name = item.get("bb_name")

        ensure_symbol_structure(symbol, original, live_dict)

        # =====================================================
        # KUCOIN STATIC FIELDS
        # =====================================================

        ku = live_dict[symbol]["kucoin"]
        ku["offline"]["value"] = True
        ku["offline"]["ts"] = now
        ku["original_name"]["value"] = original
        ku["original_name"]["ts"] = now

        ku["next_funding_at_utc"]["value"] = item.get("ku_next_funding_time")
        ku["next_funding_at_utc"]["ts"] = now

        ku["funding_interval_hr"]["value"] = item.get("funding_interval_hours")
        ku["funding_interval_hr"]["ts"] = now

        ku["tick_size"]["value"] = item.get("ku_tick_size")
        ku["tick_size"]["ts"] = now
        ku["funding_rate_decimal"]["value"] = item.get("ku_funding_rate")
        ku["funding_rate_decimal"]["ts"] = now

        ku["lot_size"]["value"] = item.get("ku_lot_size")
        ku["lot_size"]["ts"] = now

        ku["min_order_qty"]["value"] = item.get("ku_min_order_qty")
        ku["min_order_qty"]["ts"] = now

        ku["multiplier"]["value"] = item.get("ku_multiplier")
        ku["multiplier"]["ts"] = now

        ku["maker_fee"]["value"] = item.get("ku_maker_fee_rate")
        ku["maker_fee"]["ts"] = now
        ku["taker_fee"]["value"] = item.get("ku_taker_fee_rate")
        ku["taker_fee"]["ts"] = now

        # =====================================================
        # BYBIT STATIC FIELDS
        # =====================================================

        bb = live_dict[symbol]["bybit"]

        bb["offline"]["value"] = True
        bb["offline"]["ts"] = now

        bb["original_name"]["value"] = bb_name
        bb["original_name"]["ts"] = now

        bb["next_funding_at_utc"]["value"] = item.get("bb_next_funding_time")
        bb["next_funding_at_utc"]["ts"] = now

        bb["funding_interval_hr"]["value"] = item.get("funding_interval_hours")
        bb["funding_interval_hr"]["ts"] = now

        bb["tick_size"]["value"] = item.get("bb_tick_size")
        bb["tick_size"]["ts"] = now

        bb["lot_size"]["value"] = item.get("bb_lot_size")
        bb["lot_size"]["ts"] = now

        bb["min_order_qty"]["value"] = item.get("bb_min_order_qty")
        bb["min_order_qty"]["ts"] = now

        bb["funding_rate_decimal"]["value"] = item.get("bb_funding_rate")
        bb["funding_rate_decimal"]["ts"] = now

        bb["multiplier"]["value"] = BB_MULT
        bb["multiplier"]["ts"] = now

        bb["maker_fee"]["value"] = item.get("bb_maker_fee_rate") if item.get("bb_maker_fee_rate") else BB_MAKER_FEE
        bb["maker_fee"]["ts"] = now
        
        bb["taker_fee"]["value"] = item.get("bb_taker_fee_rate") if item.get("bb_taker_fee_rate") else BB_TAKER_FEE
        bb["taker_fee"]["ts"] = now