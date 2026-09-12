"""Bounded in-memory auth throttles for a single application worker.

Global and account limits work behind a proxy without trusting forwarded IP headers.
Run one worker/instance; a shared limiter is required before scaling horizontally.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from typing import Callable

from fastapi import HTTPException


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float, max_keys: int = 1, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str = "global") -> None:
        with self._lock:
            now = self.clock()
            cutoff = now - self.window
            # Buckets are ordered by their last accepted attempt. Remove inactive
            # keys, but never evict an active one to admit an attacker-chosen key.
            while self._buckets and next(iter(self._buckets.values()))[-1] <= cutoff:
                self._buckets.popitem(last=False)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    self._reject(next(iter(self._buckets.values()))[-1] + self.window - now)
                bucket = deque()
                self._buckets[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                self._reject(bucket[0] + self.window - now)
            bucket.append(now)
            self._buckets.move_to_end(key)

    @staticmethod
    def _reject(wait: float) -> None:
        retry_after = max(1, math.ceil(wait))
        raise HTTPException(
            status_code=429,
            detail=f"Too many authentication attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


login_global = SlidingWindowLimiter(limit=120, window=60)
login_account = SlidingWindowLimiter(limit=10, window=300, max_keys=1024)
registration = SlidingWindowLimiter(limit=10, window=300)


def check_login(username: str) -> None:
    login_global.check()
    login_account.check(username.strip().casefold())


def check_registration() -> None:
    registration.check()
