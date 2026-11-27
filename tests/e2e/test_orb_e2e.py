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

import contextlib
import http.server
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from rosie_fakes import clean_env, start_http, stop_http, write_config

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist"
CORE_PORT = 8765  # the page always dials this port (ui/src/protocol.ts)
PAGE_PORT = 1420  # http://localhost:1420 is an origin the core accepts (Vite's port)

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


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_port_free(port: int, timeout_s: float = 10.0) -> bool:
    """True once nothing listens on `port` (the last test's core may still be exiting)."""
    deadline = time.monotonic() + timeout_s
    while not port_free(port):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


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


class QuietFiles(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(DIST), **kwargs)

    def log_message(self, *args) -> None:
        pass


@contextlib.contextmanager
def run_core(data: Path, model_url: str) -> Iterator[Path]:
    """`rosie serve` in a subprocess, with its data in `data`. Yields the vault."""
    config = write_config(data, model_url)
    process = subprocess.Popen(
        [sys.executable, "-m", "rosie", "serve", "--config", str(config)],
        cwd=data,  # no stray .env from the repo
        env=clean_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_port(CORE_PORT, process)
        yield data / "rosie-vault"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def open_page():
    """Serves ui/dist on localhost:1420 and opens pages of it in headless Chromium."""
    for port in (CORE_PORT, PAGE_PORT):
        if not wait_port_free(port):
            skip(f"port {port} is busy (is Rosie running?)")
    page_server = start_http(QuietFiles, PAGE_PORT)
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # Playwright installed without its browser
            stop_http(page_server)
            skip(f"Chromium not available: {exc}")

        def open_(path: str = "/", size: tuple[int, int] = (380, 640)):
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.goto(f"http://localhost:{PAGE_PORT}{path}")
            return page

        try:
            yield open_
        finally:
            browser.close()
            stop_http(page_server)


@pytest.fixture
def core(open_page, model_url: str, tmp_path: Path) -> Iterator[Path]:
    with run_core(tmp_path, model_url) as vault:
        yield vault


@pytest.fixture
def deck(core: Path, open_page):
    """The Command Deck, connected to a core with the fake model."""
    page = open_page("/#deck")
    playwright_api.expect(page.get_by_text("online", exact=True)).to_be_visible(timeout=15000)
    return page


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


def test_orb_opened_before_the_core_comes_alive_when_it_starts(
    open_page, model_url: str, tmp_path: Path
) -> None:
    """At login the orb often opens first: grey, then it reconnects on its own."""
    orb = open_page("/", (200, 200)).locator(".orb")
    playwright_api.expect(orb).to_have_attribute("data-look", "offline")
    time.sleep(1.5)  # it has failed to connect at least once
    with run_core(tmp_path, model_url):
        playwright_api.expect(orb).to_have_attribute("data-look", "idle", timeout=20000)


def test_model_down_shows_unwell_and_says_what_to_run(open_page, tmp_path: Path) -> None:
    with socket.socket() as probe:  # a port nobody listens on: "Ollama is not running"
        probe.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{probe.getsockname()[1]}/v1"
    with run_core(tmp_path, dead):
        orb = open_page("/", (200, 200)).locator(".orb")
        playwright_api.expect(orb).to_have_attribute("data-look", "unwell", timeout=15000)

        deck = open_page("/#deck")
        problem = deck.get_by_label("Needs a hand")
        playwright_api.expect(problem).to_contain_text("ollama serve", timeout=15000)
        send(deck, "hello?")
        playwright_api.expect(deck.get_by_label("Conversation")).to_contain_text(
            "I can't reach my brain", timeout=15000
        )
