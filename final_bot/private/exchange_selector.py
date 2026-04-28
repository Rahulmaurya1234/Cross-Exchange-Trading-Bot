from .private_kucoin.client import KucoinFuturesClient
from .private_bybit.client import BybitClient
class ExchangeClient:

    def __init__(self, exchange: str, **credentials):

        exchange = exchange.lower()

        if exchange == "kucoin":
            

            self.client = KucoinFuturesClient(
                credentials["api_key"],
                credentials["api_secret"],
                credentials["passphrase"]
            )

        elif exchange == "bybit":
            

            self.client = BybitClient(
                credentials["api_key"],
                credentials["api_secret"]
            )

        else:
            raise ValueError("Unsupported exchange")

    async def start(self):
        await self.client.start()

    async def add_symbol(self, symbol: str):
        return await self.client.add_symbol(symbol)

    async def remove_symbol(self, symbol: str):
        if hasattr(self.client, "remove_symbol"):
            await self.client.remove_symbol(symbol)

    def get_balance(self):
        return self.client.get_balance()

    def get_account_state(self):
        return self.client.get_account_state()
    
    async def fetch_positions(self):
        return await self.client.fetch_positions()

    async def close(self):
        await self.client.close()
