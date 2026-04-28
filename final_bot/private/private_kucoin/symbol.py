import json
import uuid
import time
import asyncio


class SymbolEngine:

    def __init__(self, symbol, engine):
        self.symbol = symbol
        self.engine = engine
        self._pending_orders = {}
        self.state = {
            "position": {},
            "unrealized_pnl": 0.0,
            "liquidation_price": None,
            "mark_price": None,
            "entry_price": None,
            "side": None,
            "size": None,
            "orders": {},
            "last_update": 0
        }

    async def subscribe_topics(self):
        await self.engine.ws.send_json({
            "id": self.symbol,
            "type": "subscribe",
            "topic": f"/contract/position:{self.symbol}",
            "privateChannel": True
        })

    async def bootstrap_position_from_rest(self):
        try:
            response = await self.engine.rest.request(
                "GET",
                f"/api/v2/position?symbol={self.symbol}"
            )

            if response.get("code") != "200000":
                return

            data = response.get("data", [])

            if not data:
                return

            position = data[0]  # Kucoin returns list

            # Merge using existing logic
            self._merge_position_snapshot(position)

            # Sync derived fields
            qty = float(position.get("currentQty", 0) or 0)
            self.state["size"] = qty

            if qty > 0:
                self.state["side"] = "long"
            elif qty < 0:
                self.state["side"] = "short"
            else:
                self.state["side"] = None

            self.state["entry_price"] = float(position.get("avgEntryPrice") or 0)
            self.state["mark_price"] = float(position.get("markPrice") or 0)
            self.state["liquidation_price"] = float(position.get("liquidationPrice") or 0)
            self.state["unrealized_pnl"] = float(position.get("unrealisedPnl", 0) or 0)
            self.state["last_update"] = time.time()

            print(f"[BOOTSTRAP] Position synced for {self.symbol}")

        except Exception as e:
            print(f"[BOOTSTRAP ERROR] {self.symbol}:", e)

    async def unsubscribe_topics(self):
        await self.engine.ws.send_json({
            "id": self.symbol,
            "type": "unsubscribe",
            "topic": f"/contract/position:{self.symbol}",
            "privateChannel": True
        })

    def _merge_position_snapshot(self, data):
            pos = self.state.get("position", {})
            pos.update(data)
            self.state["position"] = pos

    def _merge_settlement_update(self, data):
        pos = self.state.get("position", {})

        if "qty" in data:
            pos["currentQty"] = data["qty"]
        if "markPrice" in data:
            pos["markPrice"] = data["markPrice"]
        # pos["fundingFee"] = data.get("fundingFee", pos.get("fundingFee"))
        # pos["fundingRate"] = data.get("fundingRate", pos.get("fundingRate"))
        self.state["position"] = pos

    async def handle_event(self, msg):

        topic = msg.get("topic", "")
        data = msg.get("data", {})
        subject = msg.get("subject","")

        if topic.startswith("/contract/position"):   

            if subject == "position.change":
                # Full snapshot update
                self._merge_position_snapshot(data)
            elif subject == "position.settlement":
                # Only funding-related fields update
                self._merge_settlement_update(data)
            elif subject == "position.adjustRiskLimit":
                # Do NOT touch position state
                return

            self.state["unrealized_pnl"] = float(data.get("unrealisedPnl", 0) or 0)
            self.state["liquidation_price"] = data.get("liquidationPrice")
            self.state["mark_price"] = data.get("markPrice")
            self.state["entry_price"] = float(data.get("avgEntryPrice", 0) or 0)

            if "currentQty" in data:
                qty = data["currentQty"]
            elif "qty" in data:
                qty = data["qty"]
            elif "size" in data:
                qty = data["size"]
            else:
                qty = 0
            self.state["size"] = qty

            if qty > 0:
                self.state["side"] = "long"
            elif qty < 0:
                self.state["side"] = "short"
            else:
                self.state["side"] = None

            self.state["last_update"] = time.time()

        elif topic.startswith("/contractMarket/tradeOrders"):

            order_id = data.get("orderId")
            if not order_id:
                return

            self.state["orders"][order_id] = data
            self.state["last_update"] = time.time()

            if order_id not in self._pending_orders:
                return

            order_tracker = self._pending_orders[order_id]
            future = order_tracker["future"]

            event_type = data.get("type")
            status = data.get("status")

            # -------------------------
            # MATCH EVENT
            # -------------------------
            if event_type == "match":

                match_size = float(data.get("matchSize", 0) or 0)
                match_price = float(data.get("matchPrice", 0) or 0)

                if match_size > 0 and match_price > 0:
                    order_tracker["total_cost"] += match_size * match_price
                    order_tracker["total_qty"] += match_size

            # -------------------------
            # FINAL EVENT
            # -------------------------
            if status == "done":

                if future.done():
                    return

                filled_size = float(data.get("filledSize", 0) or 0)

                # detect missing match events
                if filled_size > order_tracker["total_qty"]:
                    # fallback correction (best effort)
                    price = float(data.get("price", 0) or 0)

                    missing_qty = filled_size - order_tracker["total_qty"]

                    order_tracker["total_cost"] += missing_qty * price
                    order_tracker["total_qty"] += missing_qty

                future.set_result({
                    "data": data,
                    "vwap_cost": order_tracker["total_cost"],
                    "vwap_qty": order_tracker["total_qty"]
                })

    async def _execute_order(self, body, size, timeout):

        # -------------------------
        # 1️⃣ Initial REST Order
        # -------------------------
        response = await self.engine.rest.request(
            "POST",
            "/api/v1/orders",
            body
        )

        if response.get("code") != "200000":
            return {
                "success": False,
                "order_id": None,
                "error": response,
                "exchange_meta": {
                    "initial_rest_response": response,
                    "ws_or_fallback_full_response": None,
                    "confirmation_source": None
                }
            }

        order_id = response["data"]["orderId"]

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self._pending_orders[order_id] = {
            "future": future,
            "total_cost": 0.0,
            "total_qty": 0.0
        }

        confirmation_source = "ws"
        ws_full_response = None

        # -------------------------
        # 2️⃣ WS Wait / Fallback
        # -------------------------
        vwap_cost = 0
        vwap_qty = 0
        try:

            ws_full_response = await asyncio.wait_for(
                future,
                timeout=timeout
            )

            vwap_cost = ws_full_response.get("vwap_cost",0)
            vwap_qty = ws_full_response.get("vwap_qty",0)

        except asyncio.TimeoutError:

            confirmation_source = "fallback"

            ws_full_response = await self.engine.rest.request(
                "GET",
                f"/api/v1/orders/{order_id}"
            )

            if ws_full_response.get("code") != "200000":

                self._pending_orders.pop(order_id, None)

                return {
                    "success": False,
                    "order_id": order_id,
                    "error": ws_full_response,
                    "exchange_meta": {
                        "initial_rest_response": response,
                        "ws_or_fallback_full_response": ws_full_response,
                        "confirmation_source": "fallback"
                    }
                }

        finally:
            self._pending_orders.pop(order_id, None)

        # -------------------------
        # 3️⃣ Normalize Execution
        # -------------------------

        execution_object = ws_full_response.get("data", ws_full_response)

        filled_size = float(
            execution_object.get(
                "dealSize",
                execution_object.get("filledSize", 0)
            ) or 0
        )

        if vwap_qty > 0:
            avg_price = vwap_cost / vwap_qty
        else:
            avg_price = float(
                execution_object.get(
                    "avgDealPrice",
                    execution_object.get("price", 0)
                ) or 0
            )

        fee = float(execution_object.get("fee", 0) or 0)

        status = execution_object.get("status", "unknown")

        fully_filled = filled_size >= size if size else True

        return_body = {
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
                "initial_rest_response": response,
                "ws_or_fallback_full_response": ws_full_response,
                "confirmation_source": confirmation_source
            }
        }

        requested_price = execution_object.get("price",None)

        if requested_price is not None:
            return_body["requested_price"] = requested_price

        return return_body

    async def place_market(
        self,
        side: str,
        size: int,
        *,
        leverage: int | None = None,
        margin_mode: str = "ISOLATED",
        reduce_only: bool = False,
        timeout: float = 3.0
    ):

        body = {
            "clientOid": str(uuid.uuid4()),
            "symbol": self.symbol,
            "side": side,
            "type": "market",
            "size": size,
            "marginMode": margin_mode,
            "reduceOnly": reduce_only
        }

        if leverage is not None:
            body["leverage"] = leverage

        return await self._execute_order(body, size, timeout)
    

    async def place_limit_ioc(
        self,
        side: str,
        size: int,
        price: float,
        *,
        leverage: int | None = None,
        margin_mode: str = "ISOLATED",
        reduce_only: bool = False,
        timeout: float = 3.0
    ):

        body = {
            "clientOid": str(uuid.uuid4()),
            "symbol": self.symbol,
            "side": side,
            "type": "limit",
            "price": price,
            "size": size,
            "timeInForce": "IOC",
            "marginMode": margin_mode,
            "reduceOnly": reduce_only
        }

        if leverage is not None:
            body["leverage"] = leverage

        return await self._execute_order(body, size, timeout)
    

    async def cancel(self, order_id: str):
        return await self.engine.rest.request(
            "DELETE",
            f"/api/v1/orders/{order_id}"
    )


    async def close_position(self, size:int | None = None, timeout: float = 3.0):

        body = {
            "clientOid": str(uuid.uuid4()),
            "symbol": self.symbol,
            "type": "market",
            "closeOrder": True
        }

        return await self._execute_order(body, 0, timeout)
    

    async def close_position_ioc(self, price, size:int | None = None , timeout=3.0):

        body = {
            "clientOid": str(uuid.uuid4()),
            "symbol": self.symbol,
            "type": "limit",
            "price": price,
            "timeInForce": "IOC",
            "reduceOnly": True
        }

        return await self._execute_order(body, 0, timeout)

    # async def close_position(self, size: int | None = None):

        # position = self.state["position"]

        # if not position:
        #     return {
        #         "success": False,
        #         "error": "No open position",
        #         "exchange_meta": None
        #     }

        # current_qty = float(position.get("currentQty", 0) or 0)

        # if abs(current_qty) == 0:
        #     return {
        #         "success": False,
        #         "error": "No open position",
        #         "exchange_meta": None
        #     }

        # if size is not None and size <= 0:
        #     return {
        #         "success": False,
        #         "error": "Invalid close size",
        #         "exchange_meta": None
        #     }

        # close_size = abs(current_qty) if size is None else min(size, abs(current_qty))

        # if current_qty > 0:
        #     opposite_side = "sell"
        # elif current_qty < 0:
        #     opposite_side = "buy"
        # else:
        #     return {
        #         "success": False,
        #         "error": "No open position",
        #         "exchange_meta": None
        #     }

        # reuse strict-safe place_market
        # return await self.place_market(
        #     side="short",
        #     size=int(size) if size else 0,
        #     reduce_only=True,
        #     close_order = True
        # )

    def get_position(self):
        return self.state["position"]

    def get_orders(self):
        return self.state["orders"]

    def get_state(self):
        return self.state