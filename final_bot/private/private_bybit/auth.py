import time
import hmac
import hashlib


class BybitAuth:

    def __init__(self, api_key: str, api_secret: str, recv_window: int = 5000):
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = str(recv_window)

    def _timestamp(self) -> str:
        return str(int(time.time() * 1000))

    def sign(self, timestamp: str, payload: str = "") -> str:
        """
        Bybit V5 signature:
        timestamp + api_key + recv_window + payload
        """
        prehash = timestamp + self.api_key + self.recv_window + payload
        signature = hmac.new(
            self.api_secret.encode(),
            prehash.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    def headers(self, payload: str = "") -> dict:
        """
        Generate headers for REST request
        """
        timestamp = self._timestamp()
        signature = self.sign(timestamp, payload)

        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type": "application/json"
        }
