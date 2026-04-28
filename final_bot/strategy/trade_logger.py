# strategy/trade_logger.py

import os
import json
import time
from datetime import datetime
import traceback
import threading


class TradeLogger:

    def __init__(self, symbol: str):

        self.symbol = symbol
        self._lock = threading.Lock()
        self._closed = False

        # ✅ Local time (NOT UTC)
        timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        filename = f"{symbol}__{timestamp}.jsonl"

        base_dir = os.path.dirname(__file__)
        logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        self.filepath = os.path.join(logs_dir, filename)
        self._file = open(self.filepath, "a", encoding="utf-8")

        self.log_event("trade_attempt_started")

    # --------------------------------------------------
    # Internal Safe Writer
    # --------------------------------------------------

    def _write(self, payload: dict):
        if self._closed:
            return

        try:
            with self._lock:
                self._file.write(json.dumps(payload, default=str) + "\n")
                self._file.flush()
        except Exception:
            # Logging must NEVER crash trading engine
            pass

    # --------------------------------------------------
    # Timestamp Generator (Local Time + Epoch)
    # --------------------------------------------------

    def _timestamp(self):
        now = datetime.now()
        return {
            "readable": now.strftime("%Y-%m-%d %H:%M:%S"),
            "epoch": time.time()
        }

    # --------------------------------------------------
    # Safe Object Serializer
    # --------------------------------------------------

    def _safe(self, obj):
        try:
            if isinstance(obj, (str, int, float, bool)) or obj is None:
                return obj
            if isinstance(obj, dict):
                return {k: self._safe(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [self._safe(i) for i in obj]
            return str(obj)
        except Exception:
            return "UNSERIALIZABLE"

    # --------------------------------------------------
    # Public Logging APIs
    # --------------------------------------------------

    def log_event(self, event: str, *args, **data):
        payload = {
            "type": "EVENT",
            "symbol": self.symbol,
            "event": event,
            "ts": self._timestamp(),
            "args": [self._safe(a) for a in args] if args else None,
            "data": self._safe(data) if data else None
        }
        self._write(payload)

    def log_error(self, event: str, *args, **context):

        exception_info = None

        for a in args:
            if isinstance(a, Exception):
                exception_info = {
                    "type": type(a).__name__,
                    "message": str(a),
                    "traceback": traceback.format_exc()
                }

        payload = {
            "type": "ERROR",
            "symbol": self.symbol,
            "event": event,
            "ts": self._timestamp(),
            "args": [self._safe(a) for a in args] if args else None,
            "context": self._safe(context) if context else None,
            "exception": exception_info
        }

        self._write(payload)

    # --------------------------------------------------
    # Close
    # --------------------------------------------------

    def close(self):
        if self._closed:
            return

        self.log_event("trade_logger_closed")
        self._file.close()
        self._closed = True