"""End to end on the phone: the real `rosie telegram` wiring against a fake Telegram.

`run_telegram` runs exactly as on the laptop or the always-on server (agent, safety
gate, reminders, nightly review routing, rate limit), with two stand-ins: the fake
model (rosie_fakes.py) and a fake Bot API, plugged in as the httpx transport, that
plays the phone. Nothing leaves this machine and no token is real.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from rosie_fakes import write_config

import rosie.__main__ as cli

ME, STRANGER = 1111, 2222
TOKEN = "123456:fake-token-for-tests"


class FakeTelegram:
    """The Bot API's getUpdates / sendMessage, with a phone on the other end."""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.sent: list[tuple[int, str]] = []
        self.lock = threading.Lock()

    def type(self, text: str, chat: int = ME) -> None:
        """The user (or a stranger) sends a message."""
        with self.lock:
            update_id = len(self.updates) + 1
            self.updates.append(
                {"update_id": update_id, "message": {"chat": {"id": chat}, "text": text}}
            )

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert f"/bot{TOKEN}/" in request.url.path
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        if method == "getUpdates":
            offset = body.get("offset") or 0
            with self.lock:
                new = [u for u in self.updates if u["update_id"] >= offset]
            if not new:
                time.sleep(0.02)  # a real long poll would wait here
            return httpx.Response(200, json={"ok": True, "result": new})
        if method == "sendMessage":
            with self.lock:
                self.sent.append((body["chat_id"], body["text"]))
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(200, json={"ok": False, "description": f"no {method} here"})

    def replies(self) -> list[str]:
        with self.lock:
            return [text for _, text in self.sent]

    def wait_for(self, needle: str, timeout_s: float = 15.0) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for text in self.replies():
                if needle in text:
                    return text
            time.sleep(0.02)
        raise AssertionError(f"no reply containing {needle!r}; got {self.replies()}")


@pytest.fixture
def phone(tmp_path: Path, model_url: str, monkeypatch):
    """`rosie telegram` running in a thread; yields (fake Telegram, vault)."""
    config = write_config(tmp_path, model_url)
    monkeypatch.chdir(tmp_path)  # no stray .env from the repo
    telegram = FakeTelegram()
    http = httpx.Client(transport=httpx.MockTransport(telegram.handle))
    stop = threading.Event()
    environ = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": str(ME)}
    thread = threading.Thread(
        target=cli.run_telegram,
        args=(str(config), environ),
        kwargs={"stop_when": stop, "http": http},
        daemon=True,
    )
    thread.start()
    try:
        yield telegram, tmp_path / "rosie-vault"
    finally:
        stop.set()
        thread.join(timeout=10)


def test_chat_from_the_phone(phone) -> None:
    telegram, _ = phone
    telegram.type("hello from the bus")
    assert telegram.wait_for("You said: hello from the bus")


def test_task_added_from_the_phone_lands_in_the_vault(phone) -> None:
    telegram, vault = phone
    telegram.type("add a task: renew bus pass")
    telegram.wait_for("Done.")
    assert "- [ ] renew bus pass" in (vault / "tasks" / "tasks.md").read_text(encoding="utf-8")


def test_safety_gate_asks_on_the_phone_and_waits_for_yes(phone) -> None:
    telegram, vault = phone
    telegram.type("remember: my gym is at 5 pm")
    assert "Reply yes or no." in telegram.wait_for("Reply yes or no.")
    telegram.type("yes")
    telegram.wait_for("Done.")
    saved = "".join(p.read_text(encoding="utf-8") for p in (vault / "memory").glob("*.md"))
    assert "my gym is at 5 pm" in saved


def test_no_on_the_phone_means_nothing_is_saved(phone) -> None:
    telegram, vault = phone
    telegram.type("remember: my pin is 0000")
    telegram.wait_for("Reply yes or no.")
    telegram.type("no")
    telegram.wait_for("Done.")
    saved = "".join(p.read_text(encoding="utf-8") for p in (vault / "memory").glob("*.md"))
    assert "0000" not in saved


def test_strangers_get_silence(phone) -> None:
    telegram, _ = phone
    telegram.type("hi, who are you?", chat=STRANGER)
    telegram.type("ping")  # then the owner, so we know the stranger's turn has passed
    telegram.wait_for("You said: ping")
    assert all(chat == ME for chat, _ in telegram.sent)
    assert not any("who are you" in text for text in telegram.replies())
