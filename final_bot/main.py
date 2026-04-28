# # main.py
import asyncio
import os
import sys
from dotenv import load_dotenv

from private.manager import PrivateEngineManager
from strategy.entry import entry_loop
from dashboard.server import start_dashboard

from public.centre import (
    start_public_engine,
    LIVE_DATA_DICT,
    SORTED_TOP
)

# Load environment variables
load_dotenv()

KUCOIN_CREDS = {
    "api_key": os.getenv("KUCOIN_API_KEY"),
    "api_secret": os.getenv("KUCOIN_API_SECRET"),
    "passphrase": os.getenv("KUCOIN_PASSPHRASE")
}

BYBIT_CREDS = {
    "api_key": os.getenv("BYBIT_API_KEY"),
    "api_secret": os.getenv("BYBIT_API_SECRET")
}

def print_pid(): 
    PID = os.getpid()  
    print(f"[START] {sys.argv[0]} running with PID: {PID}")

print_pid()

async def main():

    private_manager = PrivateEngineManager()

    try:
        await private_manager.start(
            bybit_credentials=BYBIT_CREDS,
            kucoin_credentials=KUCOIN_CREDS
        )

        await asyncio.gather(
            start_public_engine(),
            entry_loop(
                private_manager=private_manager,
                live_data_dict=LIVE_DATA_DICT,
                sorted_top=SORTED_TOP
            ),
            private_manager.health_loop(),
            start_dashboard(private_manager)
        )
    finally:
        print("Shutting down private engines...")
        await private_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())


    
# import asyncio
# import os
# import sys
# from private.manager import PrivateEngineManager
# from strategy.entry import entry_loop
# from dashboard.server import start_dashboard

# from public.centre import (
#     start_public_engine,
#     LIVE_DATA_DICT,
#     SORTED_TOP
# )


# KUCOIN_CREDS = {
#     "api_key":"6992b24818db16000195513f",
#     "api_secret":"85330e7d-75a2-4cf8-a252-b47a0fc554be",''
#     "passphrase": "Shopgood@123"
#     }
# BYBIT_CREDS = {
#     "api_key":"XO3f5yju6kEaKn78Qu",
#     "api_secret":"QzLq1rh7EJhfunTnWPlxENanz7UuMvPLZMlX"
#      }

# def print_pid(): 
#     PID = os.getpid()  
#     print(f"[START] {sys.argv[0]} running with PID: {PID}")

# print_pid()

# async def main():

#     private_manager = PrivateEngineManager()
#     # private_manager._ready = True
#     try:
#         await private_manager.start(
#             bybit_credentials=BYBIT_CREDS,
#             kucoin_credentials=KUCOIN_CREDS
#         )

#         await asyncio.gather(
#             start_public_engine(),
#             entry_loop(
#                 private_manager=private_manager,
#                 live_data_dict=LIVE_DATA_DICT,
#                 sorted_top=SORTED_TOP
#             ),
#             private_manager.health_loop(),
#             start_dashboard(private_manager)
#         )
#     finally:
#         print("Shutting down private engines...")
#         await private_manager.stop()


# if __name__ == "__main__":
#     asyncio.run(main())