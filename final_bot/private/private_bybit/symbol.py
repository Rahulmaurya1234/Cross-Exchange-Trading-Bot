import uuid
import time
import asyncio

class SymbolEngine:

    def __init__(self, symbol: str, engine):
        self.symbol = symbol
        self.engine = engine

        self.current_leverage = None
        self._pending_orders = {}
        self.state = {
            "position": None,
            "size": 0.0,
            "side": None,
            "entry_price": None,
            "unrealized_pnl": 0.0,
            "liquidation_price": None,
            "orders": {},
            "executions": [],
            "last_update": 0
        }

    # -------------------------
    # WS Handlers
    # -------------------------

    async def handle_position(self, data):

        self.state["position"] = data
        self.state["size"] = float(data.get("size", 0))
        side = data.get("side")

        if side.lower() == "buy":
            self.state["side"] = "long"
        elif side.lower() == "sell":
            self.state["side"] = "short"

        self.state["entry_price"] = float(data.get("entryPrice", 0))
        self.state["unrealized_pnl"] = float(data.get("unrealisedPnl", 0))
        self.state["liquidation_price"] = data.get("liqPrice")
        self.state["last_update"] = time.time()
        # print("Position update:", self.symbol, self.state)


    async def handle_order(self, data):

        order_id = data.get("orderId")
        if not order_id:
            return

        self.state["orders"][order_id] = data
        self.state["last_update"] = time.time()

        # resolve pending future if exists
        if order_id in self._pending_orders:
            future = self._pending_orders[order_id]

            status = data.get("orderStatus")

            # final states
            if status in ["Filled", "Cancelled", "Rejected"]:
                if not future.done():
                    future.set_result(data)

    async def handle_execution(self, data):
        
        if len(self.state["executions"]) > 50:
            self.state["executions"].pop(0)

        self.state["executions"].append(data)
        self.state["last_update"] = time.time()


    async def set_leverage(self, leverage: int):

        body = {
            "symbol": self.symbol,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage)
        }

        response = await self.engine.rest.request(
            "POST",
            "/v5/position/set-leverage",
            body
        )

        if response["success"]:
            self.current_leverage = leverage

        return response
    

    async def _execute_order(self, body, size, timeout, leverage_meta=None):

        # -------------------------
        # 1️⃣ Initial REST Order
        # -------------------------

        response = await self.engine.rest.request(
            "POST",
            "/v5/order/create",
            body
        )

        if not response.get("success"):
            return {
                "success": False,
                "order_id": None,
                "error": response,
                "exchange_meta": {
                    "leverage_response": leverage_meta,
                    "initial_rest_response": response,
                    "ws_or_fallback_full_response": None,
                    "confirmation_source": None
                }
            }

        order_id = response["result"]["orderId"]

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self._pending_orders[order_id] = future

        confirmation_source = "ws"
        ws_full_response = None

        # -------------------------
        # 2️⃣ WS Wait / Fallback
        # -------------------------

        try:

            ws_full_response = await asyncio.wait_for(
                future,
                timeout=timeout
            )

        except asyncio.TimeoutError:

            confirmation_source = "fallback"

            fallback = await self.engine.rest.request(
                "GET",
                "/v5/order/realtime",
                {
                    "symbol": self.symbol,
                    "orderId": order_id
                }
            )

            if not fallback.get("success"):
                self._pending_orders.pop(order_id, None)

                return {
                    "success": False,
                    "order_id": order_id,
                    "error": fallback,
                    "exchange_meta": {
                        "leverage_response": leverage_meta,
                        "initial_rest_response": response,
                        "ws_or_fallback_full_response": fallback,
                        "confirmation_source": "fallback"
                    }
                }

            order_list = fallback.get("result", {}).get("list", [])

            if not order_list:
                self._pending_orders.pop(order_id, None)

                return {
                    "success": False,
                    "order_id": order_id,
                    "error": fallback,
                    "exchange_meta": {
                        "leverage_response": leverage_meta,
                        "initial_rest_response": response,
                        "ws_or_fallback_full_response": fallback,
                        "confirmation_source": "fallback"
                    }
                }

            ws_full_response = order_list[0]

        finally:

            self._pending_orders.pop(order_id, None)

        # -------------------------
        # 3️⃣ Normalize Execution
        # -------------------------

        execution_object = ws_full_response

        filled_size = float(
            execution_object.get("cumExecQty")
            or execution_object.get("execQty")
            or 0
        )

        avg_price = float(
            execution_object.get("avgPrice")
            or execution_object.get("execPrice")
            or 0
        )

        fee = float(
            execution_object.get("cumExecFee")
            or execution_object.get("execFee")
            or 0
        )

        status = execution_object.get("orderStatus", "unknown")

        fully_filled = filled_size >= size if size else True

        return {
            "success": True,
            "symbol": self.symbol,
            "order_id": order_id,
            "requested_size": size,
            "filled_size": filled_size,
            "avg_price": avg_price,
            "fee": fee,
            "status": status,
            "fully_filled": fully_filled,
            "raw": execution_object,
            "exchange_meta": {
                "leverage_response": leverage_meta,
                "initial_rest_response": response,
                "ws_or_fallback_full_response": ws_full_response,
                "confirmation_source": confirmation_source
            }
        }


    async def place_limit_ioc(
        self,
        side: str,
        size: float,
        price: float,
        *,
        leverage: int,
        reduce_only: bool = False,
        timeout: float = 3.0
    ):

        leverage_meta = None

        if leverage != self.current_leverage:

            leverage_result = await self.set_leverage(leverage)
            leverage_meta = leverage_result

            if not leverage_result.get("success") and leverage_result.get("retCode") != 110043:

                return {
                    "success": False,
                    "order_id": None,
                    "error": leverage_result,
                    "exchange_meta": {
                        "leverage_response": leverage_result,
                        "initial_rest_response": None,
                        "ws_or_fallback_full_response": None,
                        "confirmation_source": None
                    }
                }

            self.current_leverage = leverage

        body = {
            "symbol": self.symbol,
            "side": side.capitalize(),
            "orderType": "Limit",
            "price": str(price),
            "qty": str(size),
            "timeInForce": "IOC",
            "positionIdx": 0,
            "reduceOnly": reduce_only
        }

        return await self._execute_order(
            body,
            size,
            timeout,
            leverage_meta
        )

    async def place_market(
        self,
        side: str,
        size: float,
        *,
        leverage: int,
        reduce_only: bool = False,
        timeout: float = 3.0
    ):

        # -------------------------
        # 1️⃣ Ensure leverage
        # -------------------------
        leverage_meta = None

        if leverage != self.current_leverage:
            leverage_result = await self.set_leverage(leverage)
            leverage_meta = leverage_result

            # Ignore "leverage not modified" error
            if not leverage_result.get("success") and leverage_result.get("retCode") != 110043:
                return {
                    "success": False,
                    "order_id": None,
                    "error": leverage_result,
                    "exchange_meta": {
                        "leverage_response": leverage_result,
                        "initial_rest_response": None,
                        "ws_or_fallback_full_response": None,
                        "confirmation_source": None
                    }
                }

            self.current_leverage = leverage

        body = {
            "symbol": self.symbol,
            "side": side.capitalize(),
            "orderType": "Market",
            "qty": str(size),
            "timeInForce": "IOC",
            "positionIdx": 0,
            "reduceOnly": reduce_only
        }

        if reduce_only and float(size) == 0:
            body["closeOnTrigger"] = True

        return await self._execute_order(
            body,
            size,
            timeout,
            leverage_meta
        )
    
    async def close_position(self, timeout:float = 3.0, size: float | None = None):

        if self.current_leverage is None:
            return {
                "success": False,
                "error": "Leverage not set yet",
                "exchange_meta": None
            }

        current_side = self.state.get("side")

        if not current_side:
            return {
                "success": False,
                "error": "No open position",
                "exchange_meta": None
            }

        if current_side == "long":
            opposite_side = "Sell"
        elif current_side == "short":
            opposite_side = "Buy"
        else:
            return {
                "success": False,
                "error": "Invalid position side",
                "exchange_meta": None
            }

        # 🔥 Use qty=0 full close trick
        body = {
            "symbol": self.symbol,
            "side": opposite_side,
            "orderType": "Market",
            "qty": "0",
            "timeInForce": "IOC",
            "positionIdx": 0,
            "reduceOnly": True,
            "closeOnTrigger": True
        }

        return await self._execute_order(
            body,
            0,
            timeout
        )        

    async def cancel(self, order_id: str):

        body = {
            "symbol": self.symbol,
            "orderId": order_id
        }

        return await self.engine.rest.request(
            "POST",
            "/v5/order/cancel",
            body
        )

    # -------------------------
    # Exposed State
    # -------------------------

    def get_state(self):
        return self.state
