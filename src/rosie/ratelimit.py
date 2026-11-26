"""A small sliding-window rate limiter: at most N events in any `per_s` seconds.

Used where a runaway loop or a free-tier quota could hurt:

    Telegram messages in     20 a minute   (a stuck client can't flood the agent)
    orb `ask` requests       20 a minute
    cloud fallback LLM       `max_per_minute` in rosie.yaml (free tiers allow ~10-15)

Thread-safe, with an injectable clock so tests don't sleep.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self, max_events: int, per_s: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        self.max_events = max_events
        self.per_s = per_s
        self._clock = clock
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def _forget_old(self, now: float) -> None:
        while self._times and now - self._times[0] >= self.per_s:
            self._times.popleft()

    def allow(self) -> bool:
        """Count one event if there's room; False (and nothing counted) if not."""
        with self._lock:
            now = self._clock()
            self._forget_old(now)
            if len(self._times) >= self.max_events:
                return False
            self._times.append(now)
            return True

    def retry_after(self) -> float:
        """Seconds until the next event would be allowed (0 if now)."""
        with self._lock:
            now = self._clock()
            self._forget_old(now)
            if len(self._times) < self.max_events:
                return 0.0
            return max(0.0, self.per_s - (now - self._times[0]))
