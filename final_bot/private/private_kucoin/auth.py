import time
import hmac
import base64
import hashlib
import asyncio
import aiohttp


class Auth:
    BASE_URL = "https://api-futures.kucoin.com"

    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.passphrase = passphrase
        self.time_offset = 0  # server_time - local_time

    # ----------------------------
    # Time Sync (call once at boot)
    # ----------------------------
    async def sync_time(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.BASE_URL}/api/v1/timestamp") as resp:
                data = await resp.json()
                server_time = int(data["data"])

        local_time = int(time.time() * 1000)
        self.time_offset = server_time - local_time

    # ----------------------------
    # Get Correct Timestamp
    # ----------------------------
    def _get_timestamp(self) -> str:
        now = int(time.time() * 1000)
        adjusted = now + self.time_offset
        return str(adjusted)

    # ----------------------------
    # Create Signature
    # ----------------------------
    def _sign(self, str_to_sign: str) -> str:
        signature = hmac.new(
            self.api_secret,
            str_to_sign.encode(),
            hashlib.sha256
        ).digest()

        return base64.b64encode(signature).decode()

    # ----------------------------
    # Build Auth Headers
    # ----------------------------
    def build_headers(self, method: str, endpoint: str, body: str = "") -> dict:
        timestamp = self._get_timestamp()

        prehash = f"{timestamp}{method.upper()}{endpoint}{body}"
        signature = self._sign(prehash)

        passphrase_signed = self._sign(self.passphrase)

        return {
            "KC-API-KEY": self.api_key,
            "KC-API-SIGN": signature,
            "KC-API-TIMESTAMP": timestamp,
            "KC-API-PASSPHRASE": passphrase_signed,
            "KC-API-KEY-VERSION": "2",
            "Content-Type": "application/json"
        }



async def main():
    auth = Auth("", "", "")
    await auth.sync_time()

    headers = auth.build_headers("GET", "/api/v1/positions")
    print(headers)

if __name__ == "__main__":
    asyncio.run(main())
