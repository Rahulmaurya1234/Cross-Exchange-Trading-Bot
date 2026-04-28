# config.py

# ==============================
# GENERAL SETTINGS
# ==============================

ENTRY_INTERVAL = 3
MONITOR_INTERVAL = 0.3
COOLDOWN_SECONDS = 60

DEFAULT_LEVERAGE = 2
CAPITAL_FRACTION = 0.25

MAX_MARGIN_USAGE_PERCENTAGE = 0.40  # default 40%
# ==============================
# RISK SETTINGS (PLACEHOLDER)
# ==============================

MAX_DIVERGENCE_ENTRY = 0.005      # 1% entry filter
MAX_DIVERGENCE_EXIT = 0.03       # 3% hard exit

MIN_LIQ_BUFFER = 0.20            # 20% distance from liquidation

EMERGENCY_STOP = False
# ==============================
# FUNDING SETTINGS (PLACEHOLDER)
# ==============================

MIN_FUNDING_DIFF = 0.005        # placeholder threshold
TIME_REMAINED_TO_FUND = 300 # IN secs