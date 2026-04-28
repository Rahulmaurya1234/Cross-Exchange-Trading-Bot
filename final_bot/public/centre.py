import asyncio
import time

from .ku_sniper import KucoinSniper
from .bybit_sniper import BybitSniper
from .matcher import matcher
from .rest_api import( kucoin_rest_api_call, bybit_ticker_rest_api_call, bybit_instrument_rest_api_call)
from .dict_builder import dict_create_or_update
from .sorter import sorter_loop
from .funding_rollover import funding_rollover_loop

# =========================
# GLOBAL SHARED STRUCTURES
# =========================
SORTED_TOP = {}
MATCHED_LIST = []
LIVE_DATA_DICT = {}

KU_TICKER_EVENT = asyncio.Event()
KU_INS_EVENT = asyncio.Event()
BYBIT_TICKER_EVENT = asyncio.Event()
flag = True
# =========================
# MATCH LOOP
# =========================

async def match_list_loop():
    while True:
        
        try:
            KU_TICKER_EVENT.clear()
            KU_INS_EVENT.clear()
            BYBIT_TICKER_EVENT.clear()
            bybit_ticker_raw, bybit_instrument_raw, kucoin_raw = await asyncio.gather(
                bybit_ticker_rest_api_call(),
                bybit_instrument_rest_api_call(),
                kucoin_rest_api_call()
            )

            matched = matcher(bybit_ticker_raw, bybit_instrument_raw, kucoin_raw)

            MATCHED_LIST.clear()
            MATCHED_LIST.extend(matched)

            # IMPORTANT: dict build BEFORE event set
            dict_create_or_update(MATCHED_LIST, LIVE_DATA_DICT)

            KU_TICKER_EVENT.set()
            KU_INS_EVENT.set()
            BYBIT_TICKER_EVENT.set()

            await asyncio.sleep(18000)
        except Exception as e:
            print("match list loop error :",e)
            await asyncio.sleep(5)

# async def liveprint():
#     print('aagya ')
#     while LIVE_DATA_DICT.get("MANAUSDT") is None:
#         print("abhi empty h",LIVE_DATA_DICT)
#         await asyncio.sleep(5)

#     print(LIVE_DATA_DICT.get("MANAUSDT"))
    
#     while True:
#         await asyncio.sleep(15)
# =========================
# MAIN
# =========================

# =========================
# PUBLIC ENGINE STARTER
# =========================
async def safe_task(coro, name):

    while True:
        try:
            await coro()
        except Exception as e:
            print(f"{name} crashed:", e)
            await asyncio.sleep(3)


async def start_public_engine():

    ku_sniper = KucoinSniper(
        matched_list=MATCHED_LIST,
        live_dict=LIVE_DATA_DICT,
        ticker_event=KU_TICKER_EVENT,
        instrument_event=KU_INS_EVENT
    )

    bybit_sniper = BybitSniper(
        matched_list=MATCHED_LIST,
        live_dict=LIVE_DATA_DICT,
        ticker_event=BYBIT_TICKER_EVENT
    )

    tasks = [
            asyncio.create_task(safe_task(lambda: ku_sniper.run(), "kucoin ws")),
            asyncio.create_task(safe_task(lambda: bybit_sniper.run(), "bybit ws")),
            asyncio.create_task(safe_task(match_list_loop, "matcher")),
            asyncio.create_task(safe_task(lambda: sorter_loop(LIVE_DATA_DICT, SORTED_TOP), "sorter")),
            asyncio.create_task(safe_task(lambda: funding_rollover_loop(LIVE_DATA_DICT), "funding"))
        ]

    try:
        await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        print("Shutdown started")

        for t in tasks:
            t.cancel()

        await ku_sniper.close()


if __name__ == "__main__":
    asyncio.run(start_public_engine())
