# strategy/globals.py

from config import (
    MAX_DIVERGENCE_EXIT,
    COOLDOWN_SECONDS,
    MIN_FUNDING_DIFF,
    TIME_REMAINED_TO_FUND,
    MIN_LIQ_BUFFER,
    DEFAULT_LEVERAGE,
    MAX_MARGIN_USAGE_PERCENTAGE
)

# ==============================
# RUNTIME FLAGS
# ==============================

PRIVATE_READY = False
ENTRY_IN_PROGRESS = False


# ==============================
# MASTER TRADE REGISTRY
# ==============================

TRADE_REGISTRY = {}   # trade_id -> metadata
MAX_REGISTRY_HISTORY = 500


# ==============================
# TRADE STATE
# ==============================

ACTIVE_TRADES = {}     # { symbol: TradeContext }
COOLDOWN = {}          # { symbol: last_exit_timestamp }
CLOSED_TRADES = []
MAX_CLOSED_HISTORY = 100


# ==============================
# STATIC DEFAULT LIMITS (BOOT VALUES)
# ==============================

# These are initial defaults only.
# Runtime system will mirror and override these.

MAX_ACTIVE_TRADES = 3


# ==============================
# MANUAL ENTRY TOGGLE
# ==============================

class EntryControl:
    def __init__(self):
        self.allowed = False

ENTRY_CONTROL = EntryControl()


# ==============================
# GLOBAL KILL SWITCH
# ==============================

class GlobalKillSwitch:
    def __init__(self):
        self.active = False

GLOBAL_KILL_SWITCH = GlobalKillSwitch()


# ==============================
# RUNTIME CONFIG (LIVE EDITABLE)
# ==============================

class RuntimeConfig:
    def __init__(self):
        # Trade limits
        self.max_active_trades = MAX_ACTIVE_TRADES
        
        # Timing
        self.cooldown_seconds = COOLDOWN_SECONDS
        self.time_remained_to_fund = TIME_REMAINED_TO_FUND
        
        # Risk
        self.max_divergence_exit = MAX_DIVERGENCE_EXIT
        self.min_liq_buffer = MIN_LIQ_BUFFER
        
        # in RUNTIME_CONFIG (or config module)
        self.hedge_tolerance_pct = 0.003     # 0.3%
        self.qty_max_scale_up = 1.2
        self.qty_max_attempts = 6

        # Funding filter
        self.min_funding_diff = MIN_FUNDING_DIFF
        self.leverage = DEFAULT_LEVERAGE

        self.max_margin_usage_percent = MAX_MARGIN_USAGE_PERCENTAGE


RUNTIME_CONFIG = RuntimeConfig()