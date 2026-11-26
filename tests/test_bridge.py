import json
import threading
import time

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from rosie import __version__
from rosie.bridge import MAX_MESSAGE, Bridge, BridgeError, ChatHandlers, parse_message


@pytest.fixture
def bridge():
    bridge = Bridge(port=0)
    stop = threading.Event()
    thread = threading.Thread(target=bridge.run_forever, args=(stop,), daemon=True)
    thread.start()
    assert bridge.ready.wait(5)
    yield bridge
    stop.set()
    thread.join(5)


def url(bridge):
    return f"ws://127.0.0.1:{bridge.port}"


def recv(ws, kind=None, timeout=5):
    """Next message (of a given type, skipping others)."""
    while True:
        message = json.loads(ws.recv(timeout=timeout))
        if kind is None or message["type"] == kind:
            return message


def test_parse_message_accepts_objects_with_a_type():
    assert parse_message('{"type": "ping"}') == {"type": "ping"}
    assert parse_message(b'{"type": "ask", "text": "hi"}')["text"] == "hi"


@pytest.mark.parametrize("raw", ["nope", "[1, 2]", '{"text": "no type"}', '{"type": 3}'])
def test_parse_message_rejects_everything_else(raw):
    with pytest.raises(BridgeError):
        parse_message(raw)


def test_parse_message_rejects_huge_messages():
    with pytest.raises(BridgeError, match="too large"):
        parse_message('{"type": "ask", "text": "' + "x" * MAX_MESSAGE + '"}')


def test_listens_on_localhost_only():
    assert Bridge().host == "127.0.0.1"


def test_hello_then_ping_pong(bridge):
    with connect(url(bridge)) as ws:
        assert recv(ws) == {"type": "hello", "version": __version__}
        ws.send(json.dumps({"type": "ping", "id": "p1"}))
        assert recv(ws) == {"type": "pong", "id": "p1"}


def test_bad_and_unknown_messages_get_an_error_not_a_disconnect(bridge):
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send("not json")
        assert recv(ws)["type"] == "error"
        ws.send(json.dumps({"type": "launch_missiles"}))
        assert "unknown type" in recv(ws)["text"]
        ws.send(json.dumps({"type": "ping"}))
        assert recv(ws)["type"] == "pong"


def test_web_pages_from_other_origins_are_refused(bridge):
    with pytest.raises(InvalidStatus):
        connect(url(bridge), origin="https://evil.example")


def test_rosies_own_window_is_allowed(bridge):
    with connect(url(bridge), origin="http://tauri.localhost") as ws:
        assert recv(ws)["type"] == "hello"


def test_emit_reaches_every_window_from_another_thread(bridge):
    with connect(url(bridge)) as a, connect(url(bridge)) as b:
        recv(a, "hello"), recv(b, "hello")
        threading.Thread(target=bridge.emit, args=({"type": "nudge", "text": "gym"},)).start()
        assert recv(a)["text"] == "gym"
        assert recv(b)["text"] == "gym"


def test_kept_events_are_replayed_to_new_windows(bridge):
    bridge.emit({"type": "state", "state": "speaking"}, keep=True)
    bridge.emit({"type": "state", "state": "idle"}, keep=True)
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        assert recv(ws) == {"type": "state", "state": "idle"}


def test_emit_without_a_running_server_is_harmless():
    Bridge(port=0).emit({"type": "state", "state": "idle"})


def test_a_crashing_handler_reports_an_error(bridge):
    bridge.on("boom", lambda message: 1 / 0)
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "boom"}))
        assert recv(ws)["type"] == "error"


def test_slow_handlers_do_not_block_pings(bridge):
    release = threading.Event()
    bridge.on("slow", lambda message: (release.wait(5), {"type": "done"})[1])
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "slow"}))
        ws.send(json.dumps({"type": "ping"}))
        assert recv(ws)["type"] == "pong"
        release.set()
        assert recv(ws)["type"] == "done"


def test_ask_goes_through_the_agent_with_states_and_transcript(bridge):
    ChatHandlers(bridge, lambda text: f"echo: {text}")
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "ask", "text": "  hello  ", "id": 7}))
        seen = [recv(ws) for _ in range(5)]
    assert seen[0] == {"type": "transcript", "role": "you", "text": "hello"}
    assert seen[1] == {"type": "state", "state": "thinking"}
    assert seen[2] == {"type": "state", "state": "idle"}
    assert seen[3] == {"type": "transcript", "role": "rosie", "text": "echo: hello"}
    assert seen[4] == {"type": "reply", "text": "echo: hello", "id": 7}


def test_ask_failure_still_returns_the_orb_to_idle(bridge):
    def broken(text):
        raise RuntimeError("ollama down")

    ChatHandlers(bridge, broken)
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "ask", "text": "hi"}))
        recv(ws, "transcript"), recv(ws, "state")
        assert recv(ws) == {"type": "state", "state": "idle"}
        assert recv(ws)["type"] == "error"


def test_empty_ask_is_an_error(bridge):
    ChatHandlers(bridge, lambda text: "never")
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "ask", "text": "   "}))
        assert recv(ws) == {"type": "error", "text": "empty message"}


def test_confirm_round_trip(bridge):
    answers = []
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        threading.Thread(target=lambda: answers.append(bridge.ask_user("Delete it?"))).start()
        question = recv(ws, "confirm")
        assert question["question"] == "Delete it?"
        ws.send(json.dumps({"type": "confirm_reply", "id": question["id"], "allow": True}))
        for _ in range(50):
            if answers:
                break
            time.sleep(0.05)
    assert answers == [True]


def test_confirm_defaults_to_no(bridge):
    assert bridge.ask_user("Anyone there?") is False  # no window open
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        assert bridge.ask_user("Quick?", timeout_s=0.2) is False  # no answer


def test_confirm_needs_exactly_true(bridge):
    answers = []
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        thread = threading.Thread(target=lambda: answers.append(bridge.ask_user("Sure?", 5)))
        thread.start()
        question = recv(ws, "confirm")
        ws.send(json.dumps({"type": "confirm_reply", "id": question["id"], "allow": "yes"}))
        thread.join(6)
    assert answers == [False]


def free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_orb_notifier_nudges_the_orb_even_if_the_toast_fails(bridge):
    from rosie.bridge import orb_notifier

    def broken_toast(title, text):
        raise RuntimeError("no toast")

    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        orb_notifier(bridge, broken_toast)("Reminder", "gym at 6")
        assert recv(ws) == {"type": "nudge", "title": "Reminder", "text": "gym at 6"}


def test_rosie_serve_answers_on_the_websocket(tmp_path):
    from rosie.__main__ import run_serve

    config = tmp_path / "rosie.yaml"
    config.write_text(
        f"data_dir: {tmp_path.as_posix()}/data\n"
        "llm:\n  base_url: http://127.0.0.1:9/v1\n  timeout_s: 2\n"
        'day_blocks:\n  - {start: "00:00", end: "23:59", kind: gym}\n',
        encoding="utf-8",
    )
    port, stop = free_port(), threading.Event()
    thread = threading.Thread(target=run_serve, args=(str(config), port, stop), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            try:
                ws = connect(f"ws://127.0.0.1:{port}")
                break
            except OSError:
                time.sleep(0.05)
        with ws:
            assert recv(ws)["type"] == "hello"
            assert recv(ws) == {"type": "state", "state": "idle"}
            day = recv(ws, "day")  # the Day Ring, sent as soon as the core starts
            assert day["blocks"][0]["kind"] == "gym"
            ws.send(json.dumps({"type": "ask", "text": "hi"}))
            assert "Ollama" in recv(ws, "reply", timeout=20)["text"]  # no LLM here: friendly
            ws.send(json.dumps({"type": "listen"}))
            assert "voice is off" in recv(ws, "error")["text"]
    finally:
        stop.set()
        thread.join(5)


class FakeVoiceLoop:
    def __init__(self, on_state, on_transcript):
        self.on_state, self.on_transcript, self.woken = on_state, on_transcript, 0

    def wake_now(self):
        self.woken += 1
        self.on_state("listening")

    def run(self, frames):
        for _ in frames:
            pass


class FakeMic:
    def frames(self):
        return iter(())


def test_orb_voice_shows_voice_states_and_wakes_on_listen(bridge, tmp_path):
    from rosie.__main__ import start_orb_voice
    from rosie.config import RosieConfig

    made = []

    def build(config, think, on_state, on_transcript):
        made.append(FakeVoiceLoop(on_state, on_transcript))
        return made[0], FakeMic()

    loop = start_orb_voice(RosieConfig(data_dir=tmp_path), bridge, lambda t: t, build=build)
    assert loop is made[0]
    with connect(url(bridge)) as ws:
        recv(ws, "hello")
        ws.send(json.dumps({"type": "listen"}))
        assert recv(ws) == {"type": "state", "state": "listening"}
        loop.on_transcript("you", "what's next?")
        assert recv(ws) == {"type": "transcript", "role": "you", "text": "what's next?"}
    assert loop.woken == 1


def test_orb_voice_that_cannot_start_returns_none(bridge, tmp_path, capsys):
    from rosie.__main__ import start_orb_voice
    from rosie.config import RosieConfig

    def build(*args, **kwargs):
        raise ImportError("install the [voice] extras")

    assert start_orb_voice(RosieConfig(data_dir=tmp_path), bridge, str, build=build) is None
    assert "Voice off" in capsys.readouterr().out
