"""The core's health check, for the orb: the same checks as `rosie doctor`, as an event.

    {"type": "health", "ok": false, "checks": [{"name": "LLM", "status": "fail",
     "detail": "not reachable at http://localhost:11434/v1 (run `ollama serve`) ..."}]}

`rosie serve` checks once at startup, then every five minutes and whenever the orb
asks (`health`). The orb stays grey until the first result arrives, then shows a
warning ring if anything failed; the Command Deck lists what failed and how to fix it.
Like `rosie doctor`, it never includes secret values.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from rosie.doctor import Check

EVERY = timedelta(minutes=5)


def health_event(checks: list[Check]) -> dict[str, Any]:
    return {
        "type": "health",
        "ok": not any(c.status == "fail" for c in checks),
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
    }


class HealthFeed:
    def __init__(self, bridge, run_checks: Callable[[], list[Check]], every: timedelta = EVERY):
        self.bridge = bridge
        self.run_checks = run_checks
        self.every = every
        self._last_run: datetime | None = None
        bridge.on("health", lambda message: self.check())

    def check(self) -> dict[str, Any]:
        event = health_event(self.run_checks())
        self.bridge.emit(event, keep=True)
        return event

    def tick(self, now: datetime) -> None:
        if self._last_run is None or now - self._last_run >= self.every:
            self._last_run = now
            self.check()
