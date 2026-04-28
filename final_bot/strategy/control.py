# strategy/control.py

import asyncio
import strategy.globals as g


async def global_kill(private_manager):
    print("🚨 GLOBAL KILL INITIATED")

    # 1️⃣ Freeze entries immediately
    g.GLOBAL_KILL_SWITCH.active = True
    g.ENTRY_CONTROL.allowed = False

    tasks = []

    # 2️⃣ Cancel monitor tasks
    for symbol, trade in list(g.ACTIVE_TRADES.items()):
        try:
            if trade.monitor_task and not trade.monitor_task.done():
                trade.monitor_task.cancel()
        except Exception:
            pass

    # 3️⃣ Close engines from registry
    for trade_id, meta in list(g.TRADE_REGISTRY.items()):

        engines = meta.get("engines")
        trade_obj = meta.get("trade_object")

        long_engine = None
        short_engine = None

        # Prefer engines stored in registry
        if engines:
            long_engine = engines.get("long")
            short_engine = engines.get("short")

        # Fallback to trade object
        if trade_obj:
            long_engine = long_engine or getattr(trade_obj, "long_engine", None)
            short_engine = short_engine or getattr(trade_obj, "short_engine", None)

        try:
            if long_engine:
                tasks.append(long_engine.close_position())
            if short_engine:
                tasks.append(short_engine.close_position())

            meta["status"] = "FORCE_CLOSED"
            meta["exit_reason"] = "global_kill"

        except Exception as e:
            print("Kill error:", trade_id, e)

    # 4️⃣ Execute all closes concurrently
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        print("GLOBAL KILL results:", results)

    # 5️⃣ Clear only runtime active list
    g.ACTIVE_TRADES.clear()

    # 6️⃣ Unfreeze system
    g.GLOBAL_KILL_SWITCH.active = False

    print("🚨 GLOBAL KILL COMPLETE — System Ready")