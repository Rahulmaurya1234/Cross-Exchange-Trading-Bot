from .auth import BybitAuth
from .rest_client import RestClient
from .ws_client import WSClient
from .engine import TradingEngine


class BybitClient:

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.engine = None
        self.rest = None
        self.ws = None

    async def start(self):

        import asyncio

        backoff = 1

        while True:

            try:

                auth = BybitAuth(self.api_key, self.api_secret)
                self.rest = RestClient(auth)
                self.ws = WSClient(auth)

                self.engine = TradingEngine(auth, self.rest, self.ws)

                await self.engine.start()

                print("Bybit private engine started")

                return

            except Exception as e:

                print("Bybit startup failed. retrying in", backoff, "seconds:", e)

                await asyncio.sleep(backoff)

                backoff = min(backoff * 2, 15)

    async def add_symbol(self, symbol: str):
        return await self.engine.add_symbol(symbol)

    async def fetch_positions(self):

        response = await self.rest.request(
            "GET",
            "/v5/position/list",
            {"settleCoin": "USDT"}
        )

        print("inside bybit client.py fetch position",response)

        if not response.get("success"):
            return []

        result = response.get("result", {})
        data = result.get("list", [])

        positions = []

        for p in data:

            size = float(p.get("size", 0) or 0)

            if size == 0:
                continue

            side = p.get("side", "").lower()

            if side == "buy":
                side = "long"
            elif side == "sell":
                side = "short"

            positions.append({
                "symbol": p.get("symbol"),
                "size": abs(size),
                "side": side,
                "entry_price": float(p.get("avgPrice") or 0),
                "full_response_dict": p
            })

        return positions

    async def remove_symbol(self, symbol: str):
        await self.engine.remove_symbol(symbol)

    def get_account_state(self):
        return self.engine.get_account_state()

    def get_balance(self):
        return self.engine.get_balance()

    async def close(self):
        if self.engine:
            await self.engine.close()
    