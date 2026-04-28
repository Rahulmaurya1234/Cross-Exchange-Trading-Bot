import asyncio
import json
import orjson
import time
import aiohttp
import websockets
import random


class KucoinSniper:

    def __init__(self, matched_list, live_dict, ticker_event, instrument_event):
        self.matched_list = matched_list
        self.live_data = live_dict
        self.ticker_event = ticker_event
        self.instrument_event = instrument_event
        self.session = aiohttp.ClientSession()

        self.original_to_symbol = {}   # O(1) lookup map
        self.last_pong_time = {
            "ticker":0,
            "instrument":0
        }
        self.current_ticker_symbols = set()
        self.current_ins_symbols = set()

    # ==========================================================
    # PUBLIC ENTRY
    # ==========================================================
    async def close(self):
        if not self.session.closed:
            await self.session.close()

    async def run(self):
        try:
            await asyncio.gather(
                self.connection_manager("ticker"),
                self.connection_manager("instrument")
            )
        except Exception as e:
            print("kucoin whole ws crashed",e)
            raise
    # ==========================================================
    # BULLET TOKEN
    # ==========================================================

    async def connection_manager(self,topic:str):

        sleep_time = 3
        try_to_reconnect = 1

        while True :
            try : 
                await self.run_ws(topic)

                sleep_time = 3
                try_to_reconnect = 1

            except Exception as e:
                if try_to_reconnect < 7:
                    print(f"kucoin {topic} connection crashed, error : {e} ,{try_to_reconnect}st attempt. reconnecting in {sleep_time}secs...")
                    await asyncio.sleep(sleep_time)

                    if topic == "ticker":
                        
                        self.current_ticker_symbols = set()
                        self.ticker_event.set()
                        
                    elif topic == "instrument":
                        
                        self.current_ins_symbols = set()
                        self.instrument_event.set()

                    sleep_time = sleep_time + 2
                    try_to_reconnect += 1
                else : 
                    print(f"kucoin {try_to_reconnect}th attempt , can't reconnect , exiting !!")
                    raise

    async def fetch_bullet_token(self):
        url = "https://api-futures.kucoin.com/api/v1/bullet-public"

        async with self.session.post(url) as response:

            if response.status != 200:
                return None

            data = await response.json()

            if data.get("code") != "200000":
                return None

            token = data["data"]["token"]
            server = random.choice(data["data"]["instanceServers"])
            endpoint = server["endpoint"]
            return token, endpoint

    # ==========================================================
    # WS CORE
    # ==========================================================

    async def run_ws(self, topic_type: str):

        result = await self.fetch_bullet_token()
        if result is None:
            print("Failed to get bullet token")
            return

        token, endpoint = result
        ws_url = endpoint + "?token=" + token

        async with websockets.connect(
            ws_url,
            ping_interval = None,
            ping_timeout = None,
            max_queue = 2000,
            ) as ws:

            # Wait for welcome
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)

                if msg.get("type") == "welcome":
                    break

                if msg.get("type") == "error":
                    raise ConnectionError("ws welcome error")

            self.last_pong_time[topic_type]= time.time()

            ping_task = asyncio.create_task(self.ping_loop(ws, topic_type))
            recv_task = asyncio.create_task(self.receive_loop(ws, topic_type))
            sub_task  = asyncio.create_task(self.sub_loop(ws, topic_type))

            done, pending = await asyncio.wait(
                [ping_task, recv_task, sub_task],
                return_when=asyncio.FIRST_EXCEPTION
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                if task.exception():
                    raise task.exception()

    # ==========================================================
    # SUB LOOP
    # ==========================================================

    async def sub_loop(self, ws, topic_type):

        if topic_type == "ticker":
            event = self.ticker_event
            prefix = "/contractMarket/tickerV2:"
            current_symbols = self.current_ticker_symbols
        elif topic_type == "instrument":
            event = self.instrument_event
            prefix = "/contract/instrument:"
            current_symbols = self.current_ins_symbols

        while True:
            
            await event.wait()
            event.clear()

            # rebuild O(1) lookup map
            self.original_to_symbol = {
                item["original_name"]: item["symbol"]
                for item in self.matched_list
            }

            new_symbol_set = set(self.original_to_symbol.keys())
            added = new_symbol_set - current_symbols
            removed = current_symbols - new_symbol_set

            if added:
                await self.batch_sub(ws, prefix , added , topic_type)
            if removed:
                await self.batch_unsub(ws,prefix, removed, topic_type)
            
            current_symbols.clear()
            current_symbols.update(new_symbol_set)

            symbols = list(self.original_to_symbol.keys())

    async def batch_sub(self, ws, prefix, symbols, topic_type):

        batch_size = 25
        symbols = list(symbols)

        groups = [
            symbols[i:i+batch_size]
            for i in range(0, len(symbols), batch_size)
        ]

        for idx, group in enumerate(groups, start=1):

            topic_string = prefix + ",".join(group)

            msg = {
                "id": f"{topic_type}-sub-{idx}",
                "type": "subscribe",
                "topic": topic_string,
                "response": True
            }

            await ws.send(orjson.dumps(msg).decode())
            await asyncio.sleep(0.4)

            # mark offline False
            for original in group:
                symbol = self.original_to_symbol.get(original)
                if symbol:
                    self.live_data[symbol]["kucoin"]["offline"]["value"] = False
                    self.live_data[symbol]["kucoin"]["offline"]["ts"] = time.time()

    async def batch_unsub(self, ws, prefix, symbols, topic_type):

        batch_size = 25
        symbols = list(symbols)

        groups = [
            symbols[i:i+batch_size]
            for i in range(0, len(symbols), batch_size)
        ]

        for idx, group in enumerate(groups, start=1):

            topic_string = prefix + ",".join(group)

            msg = {
                "id": f"{topic_type}-unsub-{idx}",
                "type": "unsubscribe",
                "topic": topic_string,
                "response": True
            }

            await ws.send(json.dumps(msg))
            await asyncio.sleep(0.4)

            # mark offline True
            for original in group:
                symbol = self.original_to_symbol.get(original)
                if symbol:
                    self.live_data[symbol]["kucoin"]["offline"]["value"] = True
                    self.live_data[symbol]["kucoin"]["offline"]["ts"] = time.time()


    # ==========================================================
    # PING LOOP
    # ==========================================================

    async def ping_loop(self, ws,topic_type):

        while True:
            await asyncio.sleep(18)  # Kucoin pingInterval = 18000 ms

            # timeout check (10 sec from last pong)
            if time.time() - self.last_pong_time[topic_type] > 30:
                print("Pong timeout. Connection unhealthy.")
                raise ConnectionError("kucoin pong timeout")

            ping_msg = {
                "id": "ping",
                "type": "ping"
            }

            try:
                await ws.send(json.dumps(ping_msg))
            except Exception:
                raise ConnectionError("ping send failed")

    # ==========================================================
    # RECEIVE LOOP
    # ==========================================================

    async def receive_loop(self, ws, topic_type):

        while True:
            try:
                raw = await ws.recv()
            except websockets.ConnectionClosed:
                raise ConnectionError("kucoin ws closed")
            
            msg = orjson.loads(raw)

            msg_type = msg.get("type")

            if msg_type == "pong":
                self.last_pong_time[topic_type] = time.time()
                continue
            if msg_type == "ack":
                continue
            if msg_type == "welcome":
                print(f"unknown welcome: {msg}")
                continue
            if msg_type == "message":
                self.route_message(topic_type, msg)
                continue
            if msg_type == "error":
                print(f"ws error: {msg}")
                continue
            else :
                print("something unknown recieved")

            # Now guaranteed market message
            

    # ==========================================================
    # ROUTER
    # ==========================================================

    def route_message(self, topic_type, msg):

        topic = msg.get("topic")
        subject = msg.get("subject")
        data = msg.get("data")

        if not topic or not data:
            return

        original_name = topic[topic.index(":")+1:]
        mapping = self.original_to_symbol
        symbol = mapping.get(original_name)

        if not symbol:
            return

        if topic_type == "ticker":
            self.handle_ticker(symbol, data)

        elif topic_type == "instrument":
            self.handle_instrument(symbol, subject, data)

    # ==========================================================
    # TICKER HANDLER
    # ==========================================================

    def handle_ticker(self, symbol, data):

        section = self.live_data[symbol]["kucoin"]

        # Kucoin ticker timestamp usually in ms
        ts_ms = data.get("time") or data.get("timestamp")
        ts = ts_ms / 1000 if ts_ms else time.time()

        section["best_bid_price"]["value"] = data.get("bestBidPrice")
        section["best_bid_price"]["ts"] = ts

        section["best_bid_size"]["value"] = data.get("bestBidSize")
        section["best_bid_size"]["ts"] = ts

        section["best_ask_price"]["value"] = data.get("bestAskPrice")
        section["best_ask_price"]["ts"] = ts

        section["best_ask_size"]["value"] = data.get("bestAskSize")
        section["best_ask_size"]["ts"] = ts

    # ==========================================================
    # INSTRUMENT HANDLER
    # ==========================================================

    def handle_instrument(self, symbol, subject, data):

        section = self.live_data[symbol]["kucoin"]

        ts_ms = data.get("timestamp")
        ts = ts_ms / 1000 if ts_ms else time.time()

        if subject == "mark.index.price":

            section["mark_price"]["value"] = data.get("markPrice")
            section["mark_price"]["ts"] = ts

            section["index_price"]["value"] = data.get("indexPrice")
            section["index_price"]["ts"] = ts

        elif subject == "funding.rate":
            # print(f"kucoin ki funding rate aagyi : subject:{subject} , funding rate : {data.get("fundingRate")}")

            section["funding_rate_decimal"]["value"] = data.get("fundingRate")
            section["funding_rate_decimal"]["ts"] = ts
