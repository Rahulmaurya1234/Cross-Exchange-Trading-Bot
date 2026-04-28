import aiohttp
import json


class RestClient:
    BASE_URL = "https://api-futures.kucoin.com"

    def __init__(self, auth):
        self.auth = auth
        self.session = None 

    async def request(self, method: str, endpoint: str, body: dict | None = None):

        if self.session is None:
            self.session = aiohttp.ClientSession()

        body_str = json.dumps(body) if body else ""
        headers = self.auth.build_headers(method, endpoint, body_str)

        url = self.BASE_URL + endpoint

        if method.upper() == "GET":
            async with self.session.get(url, headers=headers) as response:
                data = await response.json()
                return data

        else:
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                data=body_str if body else None
            ) as response:
                data = await response.json()
                return data

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None