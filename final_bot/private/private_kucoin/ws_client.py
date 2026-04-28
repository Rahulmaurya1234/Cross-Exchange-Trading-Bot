import asyncio
import json
import websockets
import random


class WSClient:

    def __init__(self, auth, rest_client):
        self.auth = auth
        self.rest = rest_client
        self.ws = None
        self.endpoint = None
        self.token = None
        self.ping_task = None
        self.connected = False

    async def get_token(self):
        response = await self.rest.request("POST", "/api/v1/bullet-private")
        data = response["data"]
        self.token = data["token"]
        server = random.choice(data["instanceServers"])
        self.endpoint = server["endpoint"]

    async def connect(self):
        await self.get_token()
        ws_url = f"{self.endpoint}?token={self.token}"
        try:
            self.ws = await websockets.connect(ws_url)

            msg = await self.ws.recv()
            print("WS Connected:", msg)

            self.connected = True 
        except Exception:
            if self.ws:
                await self.ws.close()
            raise

        if self.ping_task:
            self.ping_task.cancel()

        self.ping_task = asyncio.create_task(self._ping_loop())


    async def _ping_loop(self):
            
        try:
            while True:
                await asyncio.sleep(20)
                await self.send_json({
                    "id": "ping",
                    "type": "ping"
                })
        except Exception as e:
            print("kucoin me ws_client ke ander ping loop me error :",e)
            return

    async def send_json(self, data: dict):
        await self.ws.send(json.dumps(data))

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