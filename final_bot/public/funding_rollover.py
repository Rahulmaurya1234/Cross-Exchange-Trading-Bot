# public/funding_rollover.py

import asyncio
import time


async def funding_rollover_loop(live_data_dict, interval=1):
    """
    Maintains funding invariant:
    Ensures next_funding_at_utc is always in the future
    based on funding_interval_hr.

    - Handles BOTH kucoin and bybit
    - Does NOT modify structure
    - Respects REST overwrites
    - Skips offline symbols
    - Safe in single asyncio event loop
    """

    while True:
        now = time.time()

        for symbol, data in live_data_dict.items():

            # 🔁 Apply same logic to both exchanges
            for exchange_name in ("kucoin", "bybit"):

                ex = data.get(exchange_name)
                if not ex:
                    continue

                # Skip offline symbols
                if ex.get("offline", {}).get("value") is True:
                    continue

                next_field = ex.get("next_funding_at_utc")
                interval_field = ex.get("funding_interval_hr")

                if not next_field or not interval_field:
                    continue

                next_funding = next_field.get("value")
                interval_hr = interval_field.get("value")

                if next_funding is None or interval_hr is None:
                    continue

                try:
                    interval_sec = int(interval_hr) * 3600
                    if interval_sec <= 0:
                        continue
                except Exception:
                    continue

                # 🔁 Rollover logic (restart-safe)
                updated = False
                try:
                    next_funding = float(next_funding)
                except Exception:
                    continue

                while now >= next_funding:
                    next_funding += interval_sec
                    updated = True

                if updated:
                    next_field["value"] = next_funding
                    next_field["ts"] = now
                    # Optional debug:
                    # print(f"Funding rolled: {symbol} [{exchange_name}] -> {next_funding}")

        await asyncio.sleep(interval)