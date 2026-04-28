import asyncio
import json
import time
from .symbol import SymbolEngine
import websockets

class TradingEngine:

    def __init__(self, auth, rest, ws):
        self.auth = auth
        self.rest = rest
        self.ws = ws

        self.listener_task = None
        self._reconnecting = False

        self.balance = 0
        self.symbols = {}
        self.account_state = {
            "available_balance": 0.0,
            "equity": 0.0,
            "last_update": 0
        }

    async def start(self):
        
        await self.ws.connect()

        try:
            overview = await self.rest.request(
                "GET",
                "/api/v1/account-overview?currency=USDT",
                {}
            )

            data = overview.get("data", {})
            print("kk balance dict :",data)
            self.account_state["available_balance"] = float(data.get("availableBalance", 0))
            self.account_state["equity"] = float(data.get("accountEquity", 0))
            self.account_state["last_update"] = time.time()

            print("Kucoin initial balance snapshot loaded")

        except Exception as e:
            print("Kucoin initial balance fetch failed:", e)

        # Subscribe global private topics
        await self.ws.send_json({
            "id": "globalOrders",
            "type": "subscribe",
            "topic": "/contractMarket/tradeOrders",
            "privateChannel": True
        })

        await self.ws.send_json({
            "id": "wallet",
            "type": "subscribe",
            "topic": "/contractAccount/wallet",
            "privateChannel": True
        })

        self.listener_task = asyncio.create_task(self._listener())

    async def _listener(self):
       
        while True:

            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=40)
                msg = json.loads(raw)
                await self._route(msg)
                
            except asyncio.TimeoutError:
                print("kucoin ws recv timeout -> reconnecting")
                await self._handle_reconnect()
                continue 

            except Exception as e:
                print("Kucoin private WS closed:", e)
                await self._handle_reconnect()
                continue

    async def _handle_reconnect(self):

        if self._reconnecting:
            return
        
        self._reconnecting = True
        print("Starting WS reconnect sequence")

        backoff = 1

        while True :
            try :
                try:
                    if self.ws and self.ws.ws:
                        await self.ws.ws.close()
                except Exception:
                    pass
                await self.ws.connect()
                print("ws reconnected")
                await self._resubscribe_all()

                self._reconnecting = False
                return 
            
            except Exception as e:
                print("Reconnect failed backoff:",backoff,"error : ",e)

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)


    async def _resubscribe_all(self):

        print("Resubscribing topics")

        # global topics

        await self.ws.send_json({
            "id": "globalOrders",
            "type": "subscribe",
            "topic": "/contractMarket/tradeOrders",
            "privateChannel": True
        })

        await self.ws.send_json({
            "id": "wallet",
            "type": "subscribe",
            "topic": "/contractAccount/wallet",
            "privateChannel": True
        })

        # wallet snapshot refresh
        await self._refresh_wallet()

        # symbol topics
        for sym in self.symbols.values():

            await sym.subscribe_topics()

            await sym.bootstrap_position_from_rest()
    

    async def _refresh_wallet(self):

        try:

            overview = await self.rest.request(
                "GET",
                "/api/v1/account-overview?currency=USDT",
                {}
            )

            data = overview.get("data", {})

            self.account_state["available_balance"] = float(data.get("availableBalance", 0))

            self.account_state["equity"] = float(data.get("accountEquity", 0))

            self.account_state["last_update"] = time.time()

        except Exception as e:

            print("Wallet refresh failed:", e)

    async def _route(self, msg):

        topic = msg.get("topic", "")

        # Wallet update
        if topic == "/contractAccount/wallet":
            wallet = msg.get("data", {})

            self.account_state["available_balance"] = float(wallet.get("availableBalance", 0))
            self.account_state["equity"] = float(wallet.get("equity", 0))
            self.account_state["last_update"] = time.time()
            return

        # tradeOrders global
        if topic.startswith("/contractMarket/tradeOrders"):
            symbol = msg["data"].get("symbol")
            if symbol in self.symbols:
                await self.symbols[symbol].handle_event(msg)
            return

        # Symbol specific topic
        if ":" in topic:
            symbol = topic.split(":")[-1]
            if symbol in self.symbols:
                await self.symbols[symbol].handle_event(msg)

    async def add_symbol(self, symbol):
        if symbol in self.symbols:
            return self.symbols[symbol]

        await self.rest.request(
            "POST",
            "/api/v2/position/changeMarginMode",
            {
                "symbol": symbol,
                "marginMode": "ISOLATED"
            }
        )


        sym = SymbolEngine(symbol, self)
        self.symbols[symbol] = sym
        await sym.bootstrap_position_from_rest()
        await asyncio.sleep(0.2)
        await sym.subscribe_topics()
        await asyncio.sleep(0.2)
        return sym

    async def remove_symbol(self, symbol):
        if symbol in self.symbols:
            await self.symbols[symbol].unsubscribe_topics()
            del self.symbols[symbol]

    def get_balance(self):
        return self.account_state["available_balance"]
    
    def get_account_state(self):
        return self.account_state

    async def close(self):
    # Close REST session
        if hasattr(self.rest, "close"):
            await self.rest.close()

        # Close websocket
        if self.ws and self.ws.ws:
            await self.ws.ws.close()

        if self.listener_task:
            self.listener_task.cancel()
            await self.listener_task
