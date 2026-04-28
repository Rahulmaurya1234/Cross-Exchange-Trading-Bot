import asyncio
import json
import time
import websockets
import hashlib
import hmac

class WSClient:

    WS_URL = "wss://stream.bybit.com/v5/private"

    def __init__(self, auth):
        self.auth = auth
        self.ws = None
        self.ping_task = None
        self.connected = False

    async def connect(self):
        try:
            self.ws = await websockets.connect(
                self.WS_URL,
                open_timeout=30,
                ping_interval=None
            )

            await self._authenticate()
            await self._subscribe_private()

            self.connected = True 
        except Exception:
            if self.ws:
                await self.ws.close()
            raise

        if self.ping_task:
            self.ping_task.cancel()

        self.ping_task = asyncio.create_task(self._ping_loop())

    async def _authenticate(self):
        expires = str(int(time.time() * 1000) + 5000)  # timestamp + small buffer
        
        prehash = "GET/realtime" + expires
        signature = hmac.new(
            self.auth.api_secret.encode(),
            prehash.encode(),
            hashlib.sha256
        ).hexdigest()

        auth_message = {
            "op": "auth",
            "args": [
                self.auth.api_key,
                expires,
                signature
            ]
        }

        await self.ws.send(json.dumps(auth_message))

        response = await self.ws.recv()
        data = json.loads(response)

        if not data.get("success"):
            raise Exception(f"WS Auth Failed: {data}")


    async def _subscribe_private(self):
        subscribe_message = {
            "op": "subscribe",
            "args": ["position", "order", "execution", "wallet"]
        }

        await self.ws.send(json.dumps(subscribe_message))

    async def _ping_loop(self):
            
        try:
            while True:
                await asyncio.sleep(20)
                await self.ws.send(json.dumps({"op": "ping"}))
        except asyncio.CancelledError:
            return
        except Exception as e:
            print("error in bybit ws_client ping loop:",e)
            return

    async def recv(self):
        try:
            return await self.ws.recv()
        except websockets.ConnectionClosed:
            self.connected = False
            raise
    
    async def close(self):

        self.connected = False

        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass

        if self.ws:
            await self.ws.close()
