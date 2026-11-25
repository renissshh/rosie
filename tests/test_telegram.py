import json
import logging
import threading

import httpx
import pytest

from rosie.__main__ import run_telegram
from rosie.logging_setup import mask_secrets
from rosie.telegram import (
    MAX_MESSAGE,
    TelegramAPI,
    TelegramBot,
    TelegramError,
    bot_from_env,
    split_message,
)

TOKEN = "123456789:" + "A" * 35
ME = 555


class FakeTelegram:
    """Plays the Bot API: queued updates in, sent messages recorded."""

    def __init__(self):
        self.updates, self.sent, self.next_id = [], [], 1

    def push(self, text, chat=ME):
        self.updates.append(
            {"update_id": self.next_id, "message": {"chat": {"id": chat}, "text": text}}
        )
        self.next_id += 1

    def handler(self, request):
        assert TOKEN in str(request.url)
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        if method == "getUpdates":
            offset = body.get("offset") or 0
            batch = [u for u in self.updates if u["update_id"] >= offset][:1]
            return httpx.Response(200, json={"ok": True, "result": batch})
        if method == "sendMessage":
            self.sent.append((body["chat_id"], body["text"]))
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(404, json={"ok": False, "description": "Not Found"})

    def bot(self, on_message=None, clock=None):
        api = TelegramAPI(TOKEN, httpx.Client(transport=httpx.MockTransport(self.handler)))
        kwargs = {"clock": clock} if clock else {}
        return TelegramBot(api, ME, on_message, poll_timeout=0, **kwargs)


def test_split_message():
    assert split_message("hi") == ["hi"]
    long = "line\n" * 2000
    parts = split_message(long)
    assert all(len(p) <= MAX_MESSAGE for p in parts)
    assert "".join(p + "\n" for p in parts).count("line") == 2000
    assert split_message("x" * (MAX_MESSAGE + 1)) == ["x" * MAX_MESSAGE, "x"]


def test_answers_only_the_allowlisted_chat(caplog):
    tg = FakeTelegram()
    tg.push("hi Rosie")
    tg.push("hack you", chat=999)
    bot = tg.bot(on_message=lambda text: f"you said {text}")
    with caplog.at_level(logging.WARNING, logger="rosie.telegram"):
        assert bot.poll_once() == 1
        assert bot.poll_once() == 0
    assert tg.sent == [(ME, "you said hi Rosie")]
    assert "TELEGRAM_CHAT_ID=999" in caplog.text


def test_updates_are_not_handled_twice():
    tg = FakeTelegram()
    tg.push("one")
    bot = tg.bot(on_message=str.upper)
    bot.poll_once()
    bot.poll_once()
    assert tg.sent == [(ME, "ONE")]


def test_crash_in_handler_is_reported_not_fatal():
    tg = FakeTelegram()
    tg.push("boom")

    def broken(text):
        raise ValueError("bad")

    tg.bot(on_message=broken).poll_once()
    assert tg.sent == [(ME, "Something went wrong on my side (ValueError).")]


@pytest.mark.parametrize("answer, allowed", [("yes", True), ("Haan!", True), ("no", False)])
def test_ask_waits_for_the_next_message(answer, allowed):
    tg = FakeTelegram()
    tg.push(answer)
    assert tg.bot().ask("Send the email?") is allowed
    assert tg.sent[0] == (ME, "Send the email?\nReply yes or no.")


def test_ask_times_out_as_no():
    tg = FakeTelegram()
    ticks = iter([0, 0, 200])
    assert tg.bot(clock=lambda: next(ticks)).ask("ok?") is False
    assert tg.sent[-1] == (ME, "No answer, so I didn't do it.")


def test_notify():
    tg = FakeTelegram()
    tg.bot().notify("Rosie", "revise DBMS")
    assert tg.sent == [(ME, "Rosie: revise DBMS")]


def test_errors_never_contain_the_token():
    def down(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    api = TelegramAPI(TOKEN, httpx.Client(transport=httpx.MockTransport(down)))
    with pytest.raises(TelegramError) as info:
        api.send_message(ME, "hi")
    assert TOKEN not in str(info.value)
    assert "ConnectError" in str(info.value)
    # and the log masker would hide it anyway
    assert TOKEN not in mask_secrets(f"url .../bot{TOKEN}/getUpdates")


def test_api_error_description():
    api = TelegramAPI(
        TOKEN,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
            )
        ),
    )
    with pytest.raises(TelegramError, match="Unauthorized"):
        api.get_updates(None)


def test_bot_from_env():
    with pytest.raises(TelegramError, match="BotFather"):
        bot_from_env({})
    with pytest.raises(TelegramError, match="numeric"):
        bot_from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "@me"})
    assert bot_from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "555"}).chat_id == 555


def test_run_forever_survives_api_errors():
    calls = []
    stop = threading.Event()

    class FlakyAPI:
        def get_updates(self, offset, timeout):
            calls.append(1)
            if len(calls) >= 3:
                stop.set()
            raise TelegramError("getUpdates failed: ConnectError")

    TelegramBot(FlakyAPI(), ME).run_forever(stop, retry_s=0)
    assert len(calls) == 3


def test_cli_without_token_explains(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert run_telegram(None, environ={}) == 1
    assert "TELEGRAM_BOT_TOKEN is not set" in capsys.readouterr().out


class VoiceTelegram(FakeTelegram):
    """Adds getFile, file download and sendVoice to the fake Bot API."""

    def __init__(self):
        super().__init__()
        self.voices = []

    def push_voice(self, file_id="v1", chat=ME):
        self.updates.append(
            {
                "update_id": self.next_id,
                "message": {"chat": {"id": chat}, "voice": {"file_id": file_id}},
            }
        )
        self.next_id += 1

    def handler(self, request):
        path = request.url.path
        if path.endswith("/getFile"):
            file_id = json.loads(request.content)["file_id"]
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": f"voice/{file_id}.oga"}}
            )
        if "/file/bot" in path:
            return httpx.Response(200, content=b"OGG:" + path.rsplit("/", 1)[-1].encode())
        if path.endswith("/sendVoice"):
            self.voices.append(request.content)
            return httpx.Response(200, json={"ok": True, "result": {}})
        return super().handler(request)


def test_voice_note_in_text_and_voice_out():
    tg = VoiceTelegram()
    tg.push_voice("abc")
    bot = tg.bot(on_message=lambda text: f"Done: {text}")
    bot.hear = lambda data: "remind me at nine" if data == b"OGG:abc.oga" else "?"
    bot.speak = lambda text: b"OPUS(" + text.encode() + b")"
    assert bot.poll_once() == 1
    assert tg.sent == [(ME, 'You said: "remind me at nine"\n\nDone: remind me at nine')]
    assert b"OPUS(Done: remind me at nine)" in tg.voices[0]
    assert b'name="chat_id"' in tg.voices[0]


def test_voice_note_without_voice_extras():
    tg = VoiceTelegram()
    tg.push_voice()
    assert tg.bot(on_message=str.upper).poll_once() == 0
    assert "can't listen to voice notes yet" in tg.sent[0][1]


def test_unhearable_voice_note_does_not_crash():
    tg = VoiceTelegram()
    tg.push_voice()
    bot = tg.bot(on_message=str.upper)

    def broken(data):
        raise RuntimeError("bad codec")

    bot.hear = broken
    assert bot.poll_once() == 0
    assert "couldn't hear" in tg.sent[0][1]


def test_failed_voice_reply_still_sends_text():
    tg = VoiceTelegram()
    tg.push_voice()
    bot = tg.bot(on_message=lambda text: "ok")
    bot.hear = lambda data: "hi"

    def broken(text):
        raise RuntimeError("no model")

    bot.speak = broken
    bot.poll_once()
    assert tg.sent and tg.voices == []
