"""The bridge between Rosie's core (Python) and the orb (Tauri + React): one WebSocket.

    orb (React) <── ws://127.0.0.1:8765 ──> Bridge ──> handlers (chat, quick log, ...)
                                              ^
          scheduler, voice loop, reminders ───┘ emit(): state, nudge, transcript ...

Every message is one JSON object with a "type". The orb sends requests
(`ask`, `ping`, `confirm_reply`, ...); the core answers and also pushes events on its
own (`state`, `nudge`, `transcript`, ...). The full list is in docs/UI.md.

Safety:
- it listens on 127.0.0.1 only, so nothing on the network can reach it;
- browsers let any web page open a WebSocket to localhost, so connections that carry
  an Origin header are refused unless it is Rosie's own window (`ALLOWED_ORIGINS`).
  Programs without a browser (tests, scripts on this laptop) send no Origin;
- messages are capped at 64 KB and must be JSON objects with a known "type".

Handlers are plain blocking functions (the agent waits on the LLM), so each one runs
in a worker thread and the bridge keeps answering pings meanwhile. `emit` is safe to
call from any thread, which is how the scheduler and the voice loop talk to the orb.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from rosie import __version__

log = logging.getLogger("rosie.bridge")

DEFAULT_PORT = 8765
MAX_MESSAGE = 64 * 1024
# Tauri serves the page from tauri://localhost (macOS/Linux) or http://tauri.localhost
# (Windows); Vite's dev server is on port 1420. None = no Origin header (not a browser).
ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    None,
]

Event = dict[str, Any]
Handler = Callable[[Event], Event | None]


class BridgeError(ValueError):
    """A message from the orb that the core can't accept."""


def parse_message(raw: str | bytes) -> Event:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if len(raw) > MAX_MESSAGE:
        raise BridgeError("message too large")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError("not JSON") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise BridgeError('expected a JSON object with a "type"')
    return message


class Bridge:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        origins: list[str | None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.origins = ALLOWED_ORIGINS if origins is None else origins
        self.handlers: dict[str, Handler] = {"ping": lambda message: {"type": "pong"}}
        self.handlers["confirm_reply"] = self._confirm_reply
        # Events every new window gets right away (latest state, today's ring, ...).
        self.snapshot: dict[str, Event] = {}
        self._clients: dict[ServerConnection, asyncio.Queue[str]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, tuple[threading.Event, list[bool]]] = {}
        self.ready = threading.Event()

    # -- wiring -------------------------------------------------------------------

    def on(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def emit(self, event: Event, keep: bool = False) -> None:
        """Send an event to every open window. Thread-safe; dropped if nobody listens.

        `keep=True` also remembers it as the latest of its type, for windows that
        connect later (the orb's state, the Day Ring).
        """
        if keep:
            self.snapshot[event["type"]] = event
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        text = json.dumps(event)
        with contextlib.suppress(RuntimeError):  # loop shutting down
            loop.call_soon_threadsafe(self._broadcast, text)

    def ask_user(self, question: str, timeout_s: float = 60.0) -> bool:
        """The safety gate's yes/no, asked in the orb. No window or no answer means no."""
        if not self._clients:
            return False
        ask_id = uuid.uuid4().hex[:8]
        answered, answer = threading.Event(), [False]
        self._pending[ask_id] = (answered, answer)
        self.emit({"type": "confirm", "id": ask_id, "question": question})
        answered.wait(timeout_s)
        self._pending.pop(ask_id, None)
        return answer[0]

    def _confirm_reply(self, message: Event) -> None:
        pending = self._pending.get(str(message.get("id")))
        if pending:
            answered, answer = pending
            answer[0] = message.get("allow") is True
            answered.set()
        return None

    # -- server -------------------------------------------------------------------

    def _broadcast(self, text: str) -> None:
        for outbox in self._clients.values():
            outbox.put_nowait(text)

    async def _writer(self, client: ServerConnection, outbox: asyncio.Queue[str]) -> None:
        """One writer per window, so messages arrive in the order they were sent."""
        try:
            while True:
                await client.send(await outbox.get())
        except ConnectionClosed:
            pass

    def _answer(self, client: ServerConnection, raw: str | bytes) -> None:
        """Run one request in a worker thread and queue its answer for that window.

        The answer is queued from this same thread, after any events the handler
        emitted, so the orb always sees "thinking ... idle" before the reply.
        """
        message: Event = {}
        try:
            message = parse_message(raw)
            handler = self.handlers.get(message["type"])
            if handler is None:
                raise BridgeError(f"unknown type {message['type']!r}")
            reply = handler(message)
        except BridgeError as exc:
            reply = {"type": "error", "text": str(exc)}
        except Exception:
            log.exception("bridge handler failed")
            reply = {"type": "error", "text": "something went wrong in Rosie's core"}
        if reply is None or self._loop is None:
            return
        if "id" in message:  # lets the orb match an answer to its request
            reply.setdefault("id", message["id"])
        text = json.dumps(reply)
        with contextlib.suppress(RuntimeError):  # loop shutting down
            self._loop.call_soon_threadsafe(self._queue_for, client, text)

    def _queue_for(self, client: ServerConnection, text: str) -> None:
        outbox = self._clients.get(client)
        if outbox is not None:
            outbox.put_nowait(text)

    async def _connection(self, client: ServerConnection) -> None:
        outbox: asyncio.Queue[str] = asyncio.Queue()
        outbox.put_nowait(json.dumps({"type": "hello", "version": __version__}))
        for event in list(self.snapshot.values()):
            outbox.put_nowait(json.dumps(event))
        self._clients[client] = outbox
        writer = asyncio.ensure_future(self._writer(client, outbox))
        try:
            async for raw in client:
                # Each message gets its own task: a slow `ask` never blocks a `ping`.
                asyncio.ensure_future(asyncio.to_thread(self._answer, client, raw))
        except ConnectionClosed:
            pass
        finally:
            self._clients.pop(client, None)
            writer.cancel()

    async def serve(self, stop: asyncio.Event) -> None:
        self._loop = asyncio.get_running_loop()
        async with serve(
            self._connection,
            self.host,
            self.port,
            origins=self.origins,  # type: ignore[arg-type]
            max_size=MAX_MESSAGE,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]  # real port when 0 was asked
            self.ready.set()
            log.info("bridge listening on ws://%s:%s", self.host, self.port)
            await stop.wait()

    def run_forever(self, stop: threading.Event) -> None:
        """Serve until `stop` is set (from any thread)."""

        async def main() -> None:
            done = asyncio.Event()
            loop = asyncio.get_running_loop()
            threading.Thread(
                target=lambda: (stop.wait(), loop.call_soon_threadsafe(done.set)), daemon=True
            ).start()
            await self.serve(done)

        asyncio.run(main())


class ChatHandlers:
    """`ask`: a typed message from the orb goes through the same agent as chat and Telegram.

    The orb is told what Rosie is doing on the way (thinking -> idle) and both sides of
    the conversation are sent as transcript lines, so the Command Deck can show them.
    """

    def __init__(self, bridge: Bridge, ask: Callable[[str], str]) -> None:
        self.bridge = bridge
        self.ask = ask
        bridge.on("ask", self.on_ask)

    def on_ask(self, message: Event) -> Event:
        text = str(message.get("text", "")).strip()
        if not text:
            raise BridgeError("empty message")
        self.bridge.emit({"type": "transcript", "role": "you", "text": text})
        self.bridge.emit({"type": "state", "state": "thinking"}, keep=True)
        try:
            reply = self.ask(text)
        finally:
            self.bridge.emit({"type": "state", "state": "idle"}, keep=True)
        self.bridge.emit({"type": "transcript", "role": "rosie", "text": reply})
        return {"type": "reply", "text": reply}


def orb_notifier(bridge: Bridge, fallback: Callable[[str, str], object] | None = None):
    """Notifications for `rosie serve`: a nudge on the orb, plus a toast/Telegram if set.

    The orb shows every nudge; the fallback (usually the desktop/phone Router) is
    best-effort, so a failing toast never loses the reminder.
    """

    def notify(title: str, text: str) -> None:
        bridge.emit({"type": "nudge", "title": title, "text": text})
        if fallback is not None:
            try:
                fallback(title, text)
            except Exception as exc:  # the orb already has it
                log.warning("fallback notification failed: %s", exc)

    return notify
