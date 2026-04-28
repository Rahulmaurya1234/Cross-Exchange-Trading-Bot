import aiohttp


# ==========================================================
# KUCOIN FUTURES REST
# ==========================================================

async def kucoin_rest_api_call():

    url = "https://api-futures.kucoin.com/api/v1/contracts/active"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:

            if resp.status != 200:
                return []

            data = await resp.json()

            if data.get("code") != "200000":
                return []

            return data.get("data", [])


# ==========================================================
# BYBIT TICKER REST
# ==========================================================

async def bybit_ticker_rest_api_call():

    url = "https://api.bybit.com/v5/market/tickers?category=linear"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:

            if resp.status != 200:
                return []

            data = await resp.json()

            if data.get("retCode") != 0:
                return []

            result = data.get("result", {})
            return result.get("list", [])


# ==========================================================
# BYBIT INSTRUMENT REST
# ==========================================================

async def bybit_instrument_rest_api_call():

    url = "https://api.bybit.com/v5/market/instruments-info?category=linear"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:

            if resp.status != 200:
                return []

            data = await resp.json()

            if data.get("retCode") != 0:
                return []

            result = data.get("result", {})
            return result.get("list", [])
