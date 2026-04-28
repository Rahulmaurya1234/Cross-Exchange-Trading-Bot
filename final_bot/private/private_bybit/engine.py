import asyncio
import json
import time
from .symbol import SymbolEngine

class TradingEngine:

    def __init__(self, auth, rest, ws):
        self.auth = auth
        self.rest = rest
        self.ws = ws

        self.listener_task = None
        self._reconnecting = False

        self.symbols = {}

        self.account_state = {
            "available_balance": 0.0,
            "equity": 0.0,
            "last_update": 0
        }

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    async def start(self):

        await self.ws.connect()

    # 🔹 FETCH INITIAL BALANCE FOR LINEAR USDT
        try:
            res = await self.rest.request(
                "GET",
                "/v5/account/wallet-balance",
                {
                    "accountType": "UNIFIED"
                }
            )

            if not res.get("success"):
                print("Wallet REST error:", res)
            else:
                result = res.get("result", {})
                list_data = result.get("list", [])

                for account in list_data:
                    coins = account.get("coin", [])
                    for coin in coins:
                        if coin.get("coin") == "USDT":

                            wallet_balance = self._safe_float(coin.get("walletBalance"))
                            total_position_im = self._safe_float(coin.get("totalPositionIM"))
                            total_order_im = self._safe_float(coin.get("totalOrderIM"))
                            locked = self._safe_float(coin.get("locked"))
                            bonus = self._safe_float(coin.get("bonus"))

                            available = (
                                wallet_balance
                                - total_position_im
                                - total_order_im
                                - locked
                                - bonus
                            )

                            self.account_state["equity"] = self._safe_float(coin.get("equity"))
                            self.account_state["available_balance"] = max(available, 0)
                            self.account_state["last_update"] = time.time()

                            print("Bybit Linear USDT balance loaded")
                            break

        except Exception as e:
            print("Bybit balance fetch failed:", e)

        self.listener_task = asyncio.create_task(self._listener())

    async def _listener(self):
        while True:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=40)
                msg = json.loads(raw)
                # print(msg)
                await self._route(msg)

            except ValueError as e:
                print("bad value got , error :",e)
                continue

            except asyncio.TimeoutError as e:
                print("bybit ws timeout ->reconnetcing , error :",e)
                await self._handle_reconnect()
                continue

            except Exception as e:
                print("WS Listener Error:", e)
                await self._handle_reconnect()
                continue

    async def _handle_reconnect(self):

        if self._reconnecting:
            return

        self._reconnecting = True

        print("Starting Bybit reconnect sequence")

        backoff = 1

        while True:

            try:

                try:
                    await self.ws.close()
                except Exception:
                    pass
                await self.ws.connect()
                print("Bybit WS reconnected")
                await self._refresh_wallet()
                self._reconnecting = False
                return
            
            except Exception as e:
                print("Reconnect failed:", e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)

    async def _refresh_wallet(self):

        try:
            res = await self.rest.request(
                "GET",
                "/v5/account/wallet-balance",
                {"accountType": "UNIFIED"}
            )

            result = res.get("result", {})
            list_data = result.get("list", [])

            for account in list_data:
                coins = account.get("coin", [])

                for coin in coins:
                    if coin.get("coin") == "USDT":

                        wallet_balance = self._safe_float(coin.get("walletBalance"))
                        total_position_im = self._safe_float(coin.get("totalPositionIM"))
                        total_order_im = self._safe_float(coin.get("totalOrderIM"))
                        locked = self._safe_float(coin.get("locked"))
                        bonus = self._safe_float(coin.get("bonus"))

                        available = (
                            wallet_balance
                            - total_position_im
                            - total_order_im
                            - locked
                            - bonus
                        )

                        self.account_state["equity"] = self._safe_float(coin.get("equity"))
                        self.account_state["available_balance"] = max(available, 0)
                        self.account_state["last_update"] = time.time()

                        return

        except Exception as e:
            print("Wallet refresh failed:", e)

    async def _route(self, msg):

        topic = msg.get("topic")

        # print("WS topic:", msg.get("topic"))

        if topic == "wallet":
            await self._handle_wallet(msg)
            return

        if topic == "position":
            for item in msg.get("data", []):
                symbol = item.get("symbol")
                if symbol in self.symbols:
                    await self.symbols[symbol].handle_position(item)
            return

        if topic == "order":
            for item in msg.get("data", []):
                symbol = item.get("symbol")
                if symbol in self.symbols:
                    await self.symbols[symbol].handle_order(item)
            return

        if topic == "execution":
            for item in msg.get("data", []):
                symbol = item.get("symbol")
                if symbol in self.symbols:
                    await self.symbols[symbol].handle_execution(item)

    async def _handle_wallet(self, msg):

        data_list = msg.get("data", [])
        if not data_list:
            return

        wallet = data_list[0]

        # always safe
        equity = self._safe_float(wallet.get("totalEquity"))

        # try aggregated field first
        available = wallet.get("totalAvailableBalance")

        if available not in (None, ""):
            available = self._safe_float(available)

        else:
            # fallback → compute from coin data
            coins = wallet.get("coin", [])

            for coin in coins:
                if coin.get("coin") == "USDT":

                    wallet_balance = self._safe_float(coin.get("walletBalance"))
                    total_position_im = self._safe_float(coin.get("totalPositionIM"))
                    total_order_im = self._safe_float(coin.get("totalOrderIM"))
                    locked = self._safe_float(coin.get("locked"))
                    bonus = self._safe_float(coin.get("bonus"))

                    available = (
                        wallet_balance
                        - total_position_im
                        - total_order_im
                        - locked
                        - bonus
                    )
                    break

        self.account_state["equity"] = equity
        self.account_state["available_balance"] = max(available, 0)
        self.account_state["last_update"] = time.time()

        print("Wallet update bybit:", self.account_state)

    async def add_symbol(self, symbol):
        if symbol in self.symbols:
            return self.symbols[symbol]

        sym = SymbolEngine(symbol, self)
        self.symbols[symbol] = sym
        return sym

    async def remove_symbol(self, symbol):
        if symbol in self.symbols:
            del self.symbols[symbol]

    def get_account_state(self):
        return self.account_state
    
    def get_balance(self):
        return self.account_state.get("available_balance")


    async def close(self):

        # stop listener task
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass

        # close websocket
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

        # close REST session
        if hasattr(self.rest, "close"):
            try:
                await self.rest.close()
            except Exception:
                pass