import asyncio 
from .auth import Auth
from .rest_client import RestClient
from .ws_client import WSClient
from .engine import TradingEngine


class KucoinFuturesClient:

    def __init__(self, api_key, secret, passphrase):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase

        self.engine = None

    async def start(self):

        backoff = 1

        while True:

            try:

                auth = Auth(self.api_key, self.secret, self.passphrase)
                await auth.sync_time()

                rest = RestClient(auth)
                ws = WSClient(auth, rest)

                self.engine = TradingEngine(auth, rest, ws)

                await self.engine.start()

                print("Kucoin private engine started")

                return

            except Exception as e:

                print("Kucoin startup failed. retrying in", backoff, "seconds:", e)

                await asyncio.sleep(backoff)

                backoff = min(backoff * 2, 15)

    async def fetch_positions(self):

        response = await self.engine.rest.request(
            "GET",
            "/api/v1/positions"
        )

        if response.get("code") != "200000":
            return []

        data = response.get("data", [])

        if data == []:
            return data

        positions = []

        for p in data:

            qty = float(p.get("currentQty", 0) or 0)

            if qty == 0:
                continue

            side = "long" if qty > 0 else "short"

            positions.append({
                "symbol": p.get("symbol"),
                "size": abs(qty),
                "side": side,
                "entry_price": float(p.get("avgEntryPrice") or 0),
                "full_response_dict": p
            })

        return positions

    async def add_symbol(self, symbol):
        return await self.engine.add_symbol(symbol)

    def get_balance(self):
        return self.engine.get_balance()
    
    def get_account_state(self):
        return self.engine.get_account_state()
    
    async def close(self):
        await self.engine.close()

    async def remove_symbol(self, symbol: str):
        await self.engine.remove_symbol(symbol)

    