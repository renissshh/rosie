"""Telegram: talk to Rosie from the phone, allowlisted to one chat.

Uses the Bot API directly over HTTPS (long polling with getUpdates), so there is
no webhook, no open port on the laptop and no extra library. Only messages from
TELEGRAM_CHAT_ID are answered; anything else is ignored and logged locally, so a
stranger who finds the bot gets silence.

Voice notes work both ways when the [voice] extras are installed: a voice note is
transcribed and answered with text plus a voice note in Rosie's voice.

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
        self._files = f"https://api.telegram.org/file/bot{token}/"
        self._http = http or httpx.Client(timeout=60)

    def _call(self, method: str, files: dict | None = None, **params: Any) -> Any:
        try:
            if files:  # multipart upload (voice notes)
                response = self._http.post(self._base + method, data=params, files=files)
            else:
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

    def download(self, file_id: str) -> bytes:
        """Fetch a file the user sent (e.g. a voice note) by its file_id."""
        path = self._call("getFile", file_id=file_id)["file_path"]
        try:
            response = self._http.get(self._files + path)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"download failed: {type(exc).__name__}") from None
        return response.content

    def send_voice(self, chat_id: int, ogg_opus: bytes) -> None:
        voice = ("rosie.ogg", ogg_opus, "audio/ogg")
        self._call("sendVoice", files={"voice": voice}, chat_id=str(chat_id))


class TelegramBot:
    def __init__(
        self,
        api: TelegramAPI,
        chat_id: int,
        on_message: Callable[[str], str] | None = None,
        poll_timeout: int = 30,
        clock: Callable[[], float] = time.monotonic,
        hear: Callable[[bytes], str] | None = None,
        speak: Callable[[str], bytes] | None = None,
    ) -> None:
        self.api = api
        self.chat_id = chat_id
        self.on_message = on_message
        self.hear = hear  # voice note bytes -> text (speech-to-text)
        self.speak = speak  # reply text -> OGG/Opus voice note (text-to-speech)
        self.poll_timeout = poll_timeout
        self._clock = clock
        self._offset: int | None = None
        self._lock = threading.Lock()  # the scheduler thread also sends

    def _texts(self, timeout: int) -> list[str]:
        return [text for text, _ in self._messages(timeout)]

    def _messages(self, timeout: int) -> list[tuple[str, bool]]:
        """New messages from the allowed chat only, as (text, was_a_voice_note)."""
        texts: list[tuple[str, bool]] = []
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
                texts.append((message["text"], False))
            elif message.get("voice") and self.hear is not None:
                heard = self._hear(message["voice"]["file_id"])
                if heard:
                    texts.append((heard, True))
                else:
                    self.send("I couldn't hear that one. Try again, or type it?")
            elif message.get("voice"):
                self.send("I can't listen to voice notes yet. Type it for me?")
        return texts

    def _hear(self, file_id: str) -> str:
        try:
            return self.hear(self.api.download(file_id)).strip()  # type: ignore[misc]
        except Exception:  # bad audio or a missing codec must not stop the bot
            log.exception("voice note could not be transcribed")
            return ""

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
        messages = self._messages(self.poll_timeout)
        for text, was_voice in messages:
            try:
                reply = self.on_message(text) if self.on_message else "I'm here."
            except Exception as exc:  # keep the bot alive whatever happens
                log.exception("telegram message failed")
                reply = f"Something went wrong on my side ({type(exc).__name__})."
            reply = reply or "(no reply)"
            if was_voice:
                reply = f'You said: "{text}"\n\n{reply}'
            self.send(reply)
            if was_voice and self.speak is not None:  # answer a voice note with one
                try:
                    voice = self.speak(reply.split("\n\n", 1)[-1])
                    with self._lock:
                        self.api.send_voice(self.chat_id, voice)
                except Exception:
                    log.exception("voice reply failed; text was sent")
        return len(messages)

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
