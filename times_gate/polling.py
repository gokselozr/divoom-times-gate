"""Keep each telemetry source independent; publish copies of completed reads."""
from __future__ import annotations

from copy import deepcopy
import threading
import time


class AsyncSource:
    def __init__(self,reader,snapshot,ready,interval=5):
        self.reader=reader
        self.snapshot=snapshot
        self.ready=ready
        self.interval=max(1,float(interval))
        self.error=""
        self.lock=threading.Lock()
        self.thread=None
        self.started_at=float("-inf")
        self.closed=False

    def request(self):
        with self.lock:
            if self.closed or (self.thread is not None and self.thread.is_alive()):
                return
            if time.monotonic()-self.started_at < self.interval:
                return
            self.started_at=time.monotonic()
            self.thread=threading.Thread(target=self._read,daemon=True,name=f"telemetry-{type(self.reader).__name__}")
            self.thread.start()

    def _read(self):
        try:
            value=deepcopy(self.reader.poll())
            with self.lock:
                if not self.closed:
                    self.snapshot=value
                    self.error=""
        except Exception as exc:
            with self.lock:
                if not self.closed:
                    self.error=type(exc).__name__
        finally:
            self.ready.set()

    def current(self):
        with self.lock:
            return deepcopy(self.snapshot),self.error

    def wait(self,timeout):
        with self.lock:
            thread=self.thread
        if thread is not None:
            thread.join(max(0,timeout))

    def close(self):
        with self.lock:
            self.closed=True
        self.ready.set()
