# private/manager.py

import asyncio
from .exchange_selector import ExchangeClient


class PrivateEngineManager:

    def __init__(self):
        self.bybit = None
        self.kucoin = None

        self._started = False
        self._ready = False

    @property
    def ready(self):
        return self._ready

    async def start(self, bybit_credentials: dict, kucoin_credentials: dict):

        if self._started:
            return

        try:
            # Create clients
            self.bybit = ExchangeClient(
                exchange="bybit",
                **bybit_credentials
            )

            self.kucoin = ExchangeClient(
                exchange="kucoin",
                **kucoin_credentials
            )

            # Start private websocket engines
            await asyncio.gather(
                self.bybit.start(),
                self.kucoin.start()
            )

            self._ready = True
            self._started = True

            print("Private Engine Ready")

        except Exception as e:
            print("Private Engine failed to start:", e)

            cleanup = []

            if self.bybit:
                cleanup.append(self.bybit.close())

            if self.kucoin:
                cleanup.append(self.kucoin.close())

            if cleanup:
                await asyncio.gather(*cleanup, return_exceptions=True)

            self._ready = False
            self._started = False
    async def fetch_positions(self):

        bybit, kucoin = await asyncio.gather(
            self.bybit.fetch_positions(),
            self.kucoin.fetch_positions()
        )

        return {
            "bybit": bybit,
            "kucoin": kucoin
        }

    async def stop(self):
        self._ready = False

        tasks = []
        if self.bybit:
            tasks.append(self.bybit.close())
        if self.kucoin:
            tasks.append(self.kucoin.close())

        if tasks:
            await asyncio.gather(*tasks)

        self._started = False

    async def health_loop(self):
        """
        Optional future extension.
        Monitor connection health.
        Auto-reconnect if needed.
        """

        while True:
            if self._started:
                # Future:
                # check ws connection state
                # if disconnected -> restart
                pass

            await asyncio.sleep(1)