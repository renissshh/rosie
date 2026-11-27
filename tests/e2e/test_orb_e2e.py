"""End to end: the real core (`rosie serve`), the real orb page, a real browser.

Only the model is fake: a tiny OpenAI-compatible server that answers like Ollama
would, with scripted tool calls. Everything between the browser and the vault on disk
is the code you ship:

    Chromium ── built ui/dist (Command Deck) ── ws://127.0.0.1:8765 ── rosie serve
                                                                         │
                         fake model (HTTP, /v1/chat/completions) <───────┤
                         temp rosie-vault/tasks, memory  <───────────────┘

Skipped unless the page is built (`cd ui && npm run build`) and Playwright with
Chromium is installed. CI runs it in the `e2e` job; see docs/TESTING.md.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist"
CORE_PORT = 8765  # the page always dials this port (ui/src/protocol.ts)
PAGE_PORT = 1420  # http://localhost:1420 is an origin the core accepts (Vite's port)
MODEL = "fake:e2e"

# CI sets ROSIE_E2E=1 so a missing piece fails the job instead of silently skipping.
REQUIRED = os.environ.get("ROSIE_E2E") == "1"


def skip(reason: str) -> None:
    if REQUIRED:
        pytest.fail(f"e2e can't run: {reason}", pytrace=False)
    pytest.skip(reason, allow_module_level=True)


try:
    from playwright import sync_api as playwright_api
except ImportError:
    skip("playwright not installed (pip install playwright)")
if not (DIST / "index.html").is_file():
    skip("orb page not built (cd ui && npm run build)")


# -- the fake model -------------------------------------------------------------------


def fake_reply(messages: list[dict]) -> dict:
    """What the model "says": a tool call for a few phrases, else plain text.

    After a tool ran, it reports the tool's result, so the test can see it came back.
    """
    last = messages[-1]
    if last["role"] == "tool":
        return {"role": "assistant", "content": f"Done. ({last['content']})"}
    text = str(last.get("content", ""))
    for prefix, tool, key in (
        ("add a task: ", "add_task", "title"),
        ("remember: ", "remember_fact", "text"),
    ):
        if text.lower().startswith(prefix):
            args = {key: text[len(prefix) :]}
            call = {
                "id": "call_1",
                "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args)},
            }
            return {"role": "assistant", "content": None, "tool_calls": [call]}
    return {"role": "assistant", "content": f"You said: {text}"}


class FakeModel(http.server.BaseHTTPRequestHandler):
    def _json(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # `rosie doctor`'s model check
        self._json({"data": [{"id": MODEL}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        message = fake_reply(request["messages"])
        self._json({"model": MODEL, "choices": [{"message": message}]})

    def log_message(self, *args) -> None:  # keep pytest output clean
        pass


def start_http(handler, port: int) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_for_port(port: int, process: subprocess.Popen, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"rosie serve exited early:\n{out}")
        if not port_free(port):
            return
        time.sleep(0.2)
    raise AssertionError(f"rosie serve did not listen on {port} in {timeout_s} s")


# -- fixtures -------------------------------------------------------------------------


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Path]:
    """`rosie serve` in a subprocess, with its data in tmp_path. Yields the vault."""
    for port in (CORE_PORT, PAGE_PORT):
        if not port_free(port):
            skip(f"port {port} is busy (is Rosie running?)")
    model = start_http(FakeModel, 0)
    vault = tmp_path / "rosie-vault"
    config = tmp_path / "rosie.yaml"
    config.write_text(
        "\n".join(
            [
                f'data_dir: "{tmp_path.as_posix()}"',
                "llm:",
                "  provider: ollama",
                f'  model: "{MODEL}"',
                f'  base_url: "http://127.0.0.1:{model.server_address[1]}/v1"',
                "day_blocks: []",
            ]
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROSIE_")}
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "rosie", "serve", "--config", str(config)],
        cwd=tmp_path,  # no stray .env from the repo
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_port(CORE_PORT, process)
        yield vault
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        model.shutdown()


@pytest.fixture
def deck(core: Path):
    """The Command Deck page in headless Chromium, connected to the core."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *args: None
    page_server = start_http(handler, PAGE_PORT)
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # Playwright installed without its browser
            page_server.shutdown()
            skip(f"Chromium not available: {exc}")
        page = browser.new_page(viewport={"width": 380, "height": 640})
        page.goto(f"http://localhost:{PAGE_PORT}/#deck")
        playwright_api.expect(page.get_by_text("online", exact=True)).to_be_visible(timeout=15000)
        try:
            yield page
        finally:
            browser.close()
            page_server.shutdown()


# -- the tests ------------------------------------------------------------------------


def send(page, text: str) -> None:
    page.get_by_label("Message Rosie").fill(text)
    page.get_by_role("button", name="Send").click()


def test_typed_message_gets_a_reply_in_the_transcript(deck) -> None:
    send(deck, "hello rosie")
    conversation = deck.get_by_label("Conversation")
    playwright_api.expect(conversation).to_contain_text("hello rosie")
    playwright_api.expect(conversation).to_contain_text("You said: hello rosie", timeout=15000)


def test_task_added_by_rosie_lands_in_the_vault_and_top3(deck, core: Path) -> None:
    send(deck, "add a task: buy a notebook")
    top3 = deck.get_by_label("Top 3 today")
    playwright_api.expect(top3).to_contain_text("buy a notebook", timeout=15000)
    tasks = (core / "tasks" / "tasks.md").read_text(encoding="utf-8")
    assert "- [ ] buy a notebook" in tasks

    deck.get_by_label("Done: buy a notebook").check()
    playwright_api.expect(top3).not_to_contain_text("buy a notebook", timeout=15000)
    assert "- [x] buy a notebook" in (core / "tasks" / "tasks.md").read_text(encoding="utf-8")


def test_safety_gate_asks_in_the_deck_and_deny_stops_the_write(deck, core: Path) -> None:
    send(deck, "remember: I train at 5 pm")
    asks = deck.get_by_label("Rosie asks")
    playwright_api.expect(asks).to_be_visible(timeout=15000)
    asks.get_by_role("button", name="Deny").click()
    playwright_api.expect(asks).to_be_hidden()
    playwright_api.expect(deck.get_by_label("Conversation")).to_contain_text("Done.", timeout=15000)
    memory = core / "memory"
    saved = "".join(p.read_text(encoding="utf-8") for p in memory.glob("*.md"))
    assert "I train at 5 pm" not in saved


def test_safety_gate_allow_saves_the_fact(deck, core: Path) -> None:
    send(deck, "remember: I train at 5 pm")
    asks = deck.get_by_label("Rosie asks")
    playwright_api.expect(asks).to_be_visible(timeout=15000)
    asks.get_by_role("button", name="Allow").click()
    playwright_api.expect(deck.get_by_label("Conversation")).to_contain_text(
        "I train at 5 pm", timeout=15000
    )
    saved = "".join(p.read_text(encoding="utf-8") for p in (core / "memory").glob("*.md"))
    assert "I train at 5 pm" in saved
