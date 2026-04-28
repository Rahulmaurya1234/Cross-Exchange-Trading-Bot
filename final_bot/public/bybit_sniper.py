import asyncio
import json
import orjson
import time
import aiohttp
import websockets


class BybitSniper:
    """
    - Single WS
    - tickers.{symbol} only
    - snapshot + delta safe
    - symbol-diff based sub / unsub
    """

    WS_URL = "wss://stream.bybit.com/v5/public/linear"

    PING_INTERVAL = 20
    BATCH_SIZE = 10
    SLEEP_BETWEEN_BATCH = 0.4

    def __init__(self, matched_list, live_dict, ticker_event):
        self.matched_list = matched_list
        self.live_data = live_dict
        self.ticker_event = ticker_event

        self.original_to_symbol = {}
        self.current_symbols = set()

        self.last_msg_time = 0

        self.ws = None
        self.last_pong = 0

    # ==========================================================
    # PUBLIC ENTRY
    # ==========================================================

    async def run(self):
        # print("bybit sniper run kar gyi ")
        sleep_time = 3
        try_to_reconnect = 1

        while True:
            try:
                await self.run_ws()

                sleep_time = 3
                try_to_reconnect = 1

            except Exception as e:
                if try_to_reconnect < 7: 

                    print(f"bybit ws connection crashed, error : {e} ,{try_to_reconnect}st attempt. reconnecting in {sleep_time}secs...")

                    await asyncio.sleep(sleep_time)

                    self.ticker_event.set()

                    sleep_time = sleep_time + 2
                    try_to_reconnect += 1

                else : 
                    print(f"bybit {try_to_reconnect}th attempt , can't reconnect , exiting !!")
                    raise

    # ==========================================================
    # WS CORE
    # ==========================================================

    async def run_ws(self):

        self.current_symbols = set()
        async with websockets.connect(
            self.WS_URL,
            ping_interval=None,
            max_queue=2000
        ) as ws:

            self.ws = ws
            self.last_pong = time.time()
            self.last_msg_time = time.time()

            ping_task = asyncio.create_task(self.ping_loop())
            recv_task = asyncio.create_task(self.recv_loop())
            sub_task  = asyncio.create_task(self.sub_loop())

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
    # PING
    # ==========================================================

    async def ping_loop(self):
        while True:
            await asyncio.sleep(self.PING_INTERVAL)

            if time.time() - self.last_msg_time > 180:
                await self.ws.close()
                raise RuntimeError("Bybit pong timeout")

            await self.ws.send(orjson.dumps({"op": "ping"}))

    # ==========================================================
    # RECEIVE
    # ==========================================================

    async def recv_loop(self):
        while True:
            try:
                raw = await self.ws.recv()
            except websockets.ConnectionClosed:
                raise RuntimeError("Bybit WS closed")
            self.last_msg_time = time.time()
            msg = orjson.loads(raw)

            # pong
            if msg.get("op") == "pong":
                # print("pong")
                self.last_pong = time.time()
                continue

            topic = msg.get("topic")
            if not topic:
                continue

            data = msg.get("data")
            if not data:
                continue
            # print("data:::::::",data)
            # topic = tickers.BTCUSDT
            original = topic.split(".",1)[1]
            # print("oringinalajfaljf",original)
            

            symbol = self.original_to_symbol.get(original)
            # print("symbol : ",symbol)
            if not symbol:
                continue

            self.handle_ticker(symbol, msg)

    # ==========================================================
    # SUB LOOP (EVENT DRIVEN)
    # ==========================================================

    async def sub_loop(self):
        while True:
            # print("inside sub loop ")
            await self.ticker_event.wait()
            # print("bybit event trigger kar gyi")
            self.ticker_event.clear()

            self.original_to_symbol = {
                item["bb_name"]: item["symbol"]
                for item in self.matched_list
            }

            new_symbols = set(self.original_to_symbol.keys())

            added = new_symbols - self.current_symbols
            removed = self.current_symbols - new_symbols

            if added:
                await self.batch_sub(added)

            if removed:
                await self.batch_unsub(removed)

            self.current_symbols.clear()
            self.current_symbols.update(new_symbols)

    # ==========================================================
    # SUB / UNSUB
    # ==========================================================

    async def batch_sub(self, originals):
        topics = [f"tickers.{o}" for o in originals]
        await self._send_batches("subscribe", topics, offline=False)

    async def batch_unsub(self, originals):
        topics = [f"tickers.{o}" for o in originals]
        await self._send_batches("unsubscribe", topics, offline=True)

    async def _send_batches(self, op, topics, offline: bool):
        batches = [
            topics[i:i + self.BATCH_SIZE]
            for i in range(0, len(topics), self.BATCH_SIZE)
        ]

        for idx, batch in enumerate(batches, start=1):
            # print("sending to bybit : ",{
            #     "op":op,
            #     "args":batch
            # })
            await self.ws.send(json.dumps({
                "op": op,
                "req_id": f"bybit-{op}-{idx}",
                "args": batch
            }))

            # offline flag update
            for topic in batch:
                original = topic.split(".")[1]
                symbol = self.original_to_symbol.get(original)
                if symbol:
                    self.live_data[symbol]["bybit"]["offline"]["value"] = offline
                    self.live_data[symbol]["bybit"]["offline"]["ts"] = time.time()

            await asyncio.sleep(self.SLEEP_BETWEEN_BATCH)

    # ==========================================================
    # TICKER HANDLER (ATOMIC UPDATES)
    # ==========================================================

    def handle_ticker(self, symbol, msg):
        section = self.live_data[symbol]["bybit"]
        # print("msgaldfkjasfj:",msg)
        data = msg.get("data", {})
        ts_ms = msg.get("ts")
        ts = ts_ms / 1000 if ts_ms else time.time()

        def upd(field, value):
            if value is None:
                return
            section[field]["value"] = value
            section[field]["ts"] = ts

        upd("best_bid_price", data.get("bid1Price"))
        upd("best_bid_size", data.get("bid1Size"))
        upd("best_ask_price", data.get("ask1Price"))
        upd("best_ask_size", data.get("ask1Size"))
        # print(f"maket price : {data.get("markPrice")}")
        upd("mark_price", data.get("markPrice"))
        upd("index_price", data.get("indexPrice"))

        upd("funding_rate_decimal", data.get("fundingRate"))
        # print(f"funding rate bybit ki aagyi : {data.get("fundingRate")}")
        nft = data.get("nextFundingTime")
        if nft:
            upd("next_funding_at_utc", int(nft)/1000)
