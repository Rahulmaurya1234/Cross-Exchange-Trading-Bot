# strategy/trade_context.py

import time


class TradeContext:

    def __init__(
        self,
        symbol_name,
        long_engine,
        short_engine,
        long_exchange,
        short_exchange,
        bb_qty,
        ku_qty,
        bb_notional,
        ku_notional,
        entry_price_long,
        entry_price_short,
        long_leg ,
        short_leg,
        entry_dominant_exchange,
        entry_funding_sign,
        bb_funding,
        ku_funding,
        entry_funding_difference,
        mult_b,
        mult_k,
        base_exposure ,
        trade_id ,
        entry_div_percent
    ):
        self.symbol = symbol_name
        self.exit_reason = None

        self.long_engine = long_engine
        self.short_engine = short_engine

        self.long_exchange=long_exchange
        self.short_exchange=short_exchange

        self.bb_qty=bb_qty
        self.ku_qty = ku_qty
        self.bb_notional = bb_notional
        self.ku_notional = ku_notional
        

        self.entry_price_long = entry_price_long
        self.entry_price_short = entry_price_short

        # funding metadata
        self.entry_dominant_exchange = entry_dominant_exchange
        self.entry_funding_sign = entry_funding_sign
        self.bb_funding = bb_funding
        self.ku_funding = ku_funding
        self.entry_funding_difference = entry_funding_difference
        self.status = "ACTIVE"  # ACTIVE / CLOSING / CLOSED

        self.long_leg = long_leg
        self.short_leg = short_leg

        #persistency layer : 
        # strategy/trade_context.py

        self.entry_div_percent = entry_div_percent

        self.unrealized_pnl = 0.0
        self.realized_pnl = None
        self.closed_at = None
        self.total_fees = 0.0

        self.mult_b = mult_b
        self.mult_k = mult_k
        self.base_exposure = base_exposure
        self.trade_id = trade_id

        self.created_at = time.time()

        self.monitor_task = None