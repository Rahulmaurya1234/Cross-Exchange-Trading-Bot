import json
import aiohttp


class RestClient:

    BASE_URL = "https://api.bybit.com"

    def __init__(self, auth):
        self.auth = auth
        self.session = None

    async def request(self, method: str, path: str, params: dict | None = None):
        """
        Generic REST request for Bybit V5
        """
        if self.session is None:
            self.session = aiohttp.ClientSession()
        url = self.BASE_URL + path
        params = params or {}

        # Bybit requires category for trading endpoints
        if path.startswith("/v5/order") or path.startswith("/v5/position"):
            params.setdefault("category", "linear")

        if method.upper() == "GET":
            query_string = "&".join(
                f"{k}={v}" for k, v in sorted(params.items())
            )
            payload = query_string
            headers = self.auth.headers(payload)

            if query_string:
                url += "?" + query_string
            
            async with self.session.get(url, headers=headers) as resp:
                return await self._handle_response(resp)

        else:
            body = json.dumps(params, separators=(',', ':'), sort_keys=True)
            headers = self.auth.headers(body)

            
            async with self.session.post(url, headers=headers, data=body) as resp:
                return await self._handle_response(resp)

    async def _handle_response(self, resp):
        data = await resp.json()

        # Bybit success condition
        if data.get("retCode") != 0:
            return {
                "success": False,
                "retCode": data.get("retCode"),
                "retMsg": data.get("retMsg")
            }

        return {
            "success": True,
            "result": data.get("result")
        }
    
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
