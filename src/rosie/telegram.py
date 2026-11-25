"""Telegram: talk to Rosie from the phone, allowlisted to one chat.

Uses the Bot API directly over HTTPS (long polling with getUpdates), so there is
no webhook, no open port on the laptop and no extra library. Only messages from
TELEGRAM_CHAT_ID are answered; anything else is ignored and logged locally, so a
stranger who finds the bot gets silence.

The bot token is a secret: it is read from the env var named in the config, and
it is part of every API URL, so errors are rewritten to never include the URL.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

log = logging.getLogger("rosie.telegram")

MAX_MESSAGE = 4096  # Telegram's limit per message
YES = {"y", "yes", "haan", "ha", "ok", "okay", "sure"}


class TelegramError(RuntimeError):
    """The Telegram API failed. Never contains the token."""


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split long replies at line breaks where possible."""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return [*chunks, text] if text or not chunks else chunks


class TelegramAPI:
    def __init__(self, token: str, http: httpx.Client | None = None) -> None:
        if not token:
            raise TelegramError("no bot token")
        self._base = f"https://api.telegram.org/bot{token}/"
        self._http = http or httpx.Client(timeout=60)

    def _call(self, method: str, **params: Any) -> Any:
        try:
            response = self._http.post(self._base + method, json=params)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # str(exc) can contain the URL, which contains the token: report the type only
            raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
        if not body.get("ok"):
            raise TelegramError(f"{method} failed: {body.get('description', 'unknown error')}")
        return body["result"]

    def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", **params)

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            self._call("sendMessage", chat_id=chat_id, text=chunk)


class TelegramBot:
    def __init__(
        self,
        api: TelegramAPI,
        chat_id: int,
        on_message: Callable[[str], str] | None = None,
        poll_timeout: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api = api
        self.chat_id = chat_id
        self.on_message = on_message
        self.poll_timeout = poll_timeout
        self._clock = clock
        self._offset: int | None = None
        self._lock = threading.Lock()  # the scheduler thread also sends

    def _texts(self, timeout: int) -> list[str]:
        """Fetch new updates; return texts from the allowed chat only."""
        texts = []
        for update in self.api.get_updates(self._offset, timeout):
            self._offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat = (message.get("chat") or {}).get("id")
            if chat != self.chat_id:
                log.warning(
                    "ignored a message from unknown chat %s "
                    "(if this is you, set TELEGRAM_CHAT_ID=%s in .env)",
                    chat,
                    chat,
                )
                continue
            if message.get("text"):
                texts.append(message["text"])
        return texts

    def send(self, text: str) -> None:
        with self._lock:
            self.api.send_message(self.chat_id, text)

    def notify(self, title: str, text: str) -> None:
        self.send(f"{title}: {text}")

    def ask(self, question: str, wait_s: float = 120) -> bool:
        """Yes/no for the safety gate: ask, then wait for the next message. Silence is no."""
        self.send(f"{question}\nReply yes or no.")
        deadline = self._clock() + wait_s
        while self._clock() < deadline:
            texts = self._texts(timeout=min(self.poll_timeout, 10))
            if texts:
                return texts[0].strip().lower().rstrip("!.") in YES
        self.send("No answer, so I didn't do it.")
        return False

    def poll_once(self) -> int:
        """Answer every new message. Returns how many were handled."""
        texts = self._texts(self.poll_timeout)
        for text in texts:
            try:
                reply = self.on_message(text) if self.on_message else "I'm here."
            except Exception as exc:  # keep the bot alive whatever happens
                log.exception("telegram message failed")
                reply = f"Something went wrong on my side ({type(exc).__name__})."
            self.send(reply or "(no reply)")
        return len(texts)

    def run_forever(self, stop: threading.Event, retry_s: float = 5.0) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except TelegramError as exc:
                log.warning("telegram poll failed, retrying: %s", exc)
                stop.wait(retry_s)


def bot_from_env(
    environ: Mapping[str, str],
    token_env: str = "TELEGRAM_BOT_TOKEN",
    chat_id_env: str = "TELEGRAM_CHAT_ID",
    http: httpx.Client | None = None,
) -> TelegramBot:
    token = environ.get(token_env, "")
    chat = environ.get(chat_id_env, "")
    if not token:
        raise TelegramError(f"{token_env} is not set in .env (get one from @BotFather)")
    try:
        chat_id = int(chat)
    except ValueError:
        raise TelegramError(f"{chat_id_env} must be your numeric chat id") from None
    return TelegramBot(TelegramAPI(token, http), chat_id)
