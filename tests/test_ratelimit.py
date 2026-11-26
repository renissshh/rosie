import json
import threading

import httpx
import pytest
from websockets.sync.client import connect

from rosie.__main__ import telegram_reply
from rosie.bridge import Bridge, ChatHandlers
from rosie.config import LLMConfig
from rosie.llm import LLMError, OpenAICompatibleLLM
from rosie.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_allows_n_per_window_then_waits():
    clock = Clock()
    limit = RateLimiter(3, per_s=60, clock=clock)
    for _ in range(3):
        assert limit.allow()
        clock.t += 10  # events at 1000, 1010, 1020
    assert not limit.allow()  # at 1030: three in the last minute
    assert limit.retry_after() == 30  # the 1000 one leaves at 1060
    clock.t = 1060
    assert limit.allow()
    assert not limit.allow()
    assert limit.retry_after() == 10  # next to leave: 1010, at 1070


def test_a_refused_event_is_not_counted():
    clock = Clock()
    limit = RateLimiter(1, per_s=10, clock=clock)
    limit.allow()
    for _ in range(5):
        limit.allow()
    clock.t += 10
    assert limit.allow()


def test_needs_a_positive_limit():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_thread_safe_count():
    limit = RateLimiter(100, per_s=3600)
    results = []
    threads = [threading.Thread(target=lambda: results.append(limit.allow())) for _ in range(150)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 100


def test_cloud_fallback_stays_under_its_quota():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    llm = OpenAICompatibleLLM(
        LLMConfig(provider="openai_compatible", model="gemini", max_per_minute=2),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        environ={},
    )
    llm.chat([{"role": "user", "content": "a"}])
    llm.chat([{"role": "user", "content": "b"}])
    with pytest.raises(LLMError, match="rate limit"):
        llm.chat([{"role": "user", "content": "c"}])
    assert len(calls) == 2  # the third never left the laptop


def test_local_model_has_no_limit_by_default():
    assert OpenAICompatibleLLM(LLMConfig()).limiter is None


class FakeReview:
    active = False


class FakeSession:
    def ask(self, text):
        return type("R", (), {"text": f"chat: {text}"})()


def test_telegram_flood_gets_a_slow_down():
    clock = Clock()
    limit = RateLimiter(2, per_s=60, clock=clock)
    answers = [telegram_reply("hi", FakeReview(), FakeSession(), limit) for _ in range(3)]
    assert answers[:2] == ["chat: hi", "chat: hi"]
    assert answers[2] == "Slow down a little: try again in 60 s."


def test_orb_asks_are_limited_too():
    bridge = Bridge(port=0)
    stop = threading.Event()
    threading.Thread(target=bridge.run_forever, args=(stop,), daemon=True).start()
    bridge.ready.wait(5)
    ChatHandlers(bridge, lambda text: "ok", limiter=RateLimiter(1, per_s=60))
    try:
        with connect(f"ws://127.0.0.1:{bridge.port}") as ws:
            json.loads(ws.recv(timeout=5))  # hello
            ws.send(json.dumps({"type": "ask", "text": "one"}))
            ws.send(json.dumps({"type": "ask", "text": "two"}))
            seen = []
            while not ({"reply", "error"} <= {m["type"] for m in seen}):
                seen.append(json.loads(ws.recv(timeout=5)))
    finally:
        stop.set()
    errors = [m["text"] for m in seen if m["type"] == "error"]
    assert len(errors) == 1 and errors[0].startswith("too many messages; try again in")
