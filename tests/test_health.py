from datetime import datetime, timedelta

from rosie.doctor import Check
from rosie.health import HealthFeed, health_event


class FakeBridge:
    def __init__(self):
        self.handlers, self.sent = {}, []

    def on(self, kind, handler):
        self.handlers[kind] = handler

    def emit(self, event, keep=False):
        self.sent.append((event, keep))


GOOD = [Check("Python", "ok", "3.12"), Check("Your vault", "warn", "not set")]
BAD = [Check("Python", "ok", "3.12"), Check("LLM", "fail", "not reachable (run `ollama serve`)")]


def test_warnings_are_still_ok_failures_are_not():
    assert health_event(GOOD)["ok"] is True
    event = health_event(BAD)
    assert event["ok"] is False
    assert event["checks"][1] == {
        "name": "LLM",
        "status": "fail",
        "detail": "not reachable (run `ollama serve`)",
    }


def test_checks_at_start_then_every_five_minutes():
    runs = []
    bridge = FakeBridge()
    feed = HealthFeed(bridge, lambda: runs.append(1) or GOOD)
    start = datetime(2026, 11, 26, 20, 0)
    feed.tick(start)
    feed.tick(start + timedelta(minutes=4))
    feed.tick(start + timedelta(minutes=5))
    assert len(runs) == 2
    assert all(keep for _, keep in bridge.sent)  # late windows get the last result


def test_the_orb_can_ask_any_time():
    bridge = FakeBridge()
    HealthFeed(bridge, lambda: BAD)
    reply = bridge.handlers["health"]({"type": "health"})
    assert reply["ok"] is False
