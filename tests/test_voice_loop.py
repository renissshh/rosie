import builtins
import math
from array import array

from rosie.__main__ import main
from rosie.audio import SAMPLE_RATE, frames_of
from rosie.stt import Transcript
from rosie.voice_loop import VoiceLoop


def tone(ms, amplitude=6000):
    n = SAMPLE_RATE * ms // 1000
    return array(
        "h", (int(amplitude * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE)) for i in range(n))
    ).tobytes()


def quiet(ms):
    return b"\0\0" * (SAMPLE_RATE * ms // 1000)


class WakeOnFrame:
    """Wakes on the n-th frame fed, optionally with a request already heard."""

    def __init__(self, at=1, request=None):
        self.at, self.n, self.request = at, 0, request

    def feed(self, frame):
        self.n += 1
        return self.n == self.at


class STT:
    def __init__(self, *texts):
        self.texts = list(texts)

    def transcribe(self, pcm):
        return Transcript(self.texts.pop(0), len(pcm) / 32000, 0.1)


class FakePlayer:
    def __init__(self, frames_long=10):
        self.frames_long, self.left, self.started, self.stopped = frames_long, 0, [], 0

    def start(self, pcm, rate):
        self.started.append((len(pcm), rate))
        self.left = self.frames_long

    def is_playing(self):
        self.left -= 1
        return self.left > 0

    def stop(self):
        self.stopped += 1
        self.left = 0


def make(wake=None, stt=None, player=None, think=None):
    states = []
    loop = VoiceLoop(
        wake or WakeOnFrame(),
        stt or STT("what's on today"),
        think or (lambda text: f"reply to {text}"),
        lambda text: (b"\0\0" * 100, 24_000),
        player or FakePlayer(),
        on_state=states.append,
    )
    return loop, states


def feed(loop, audio):
    for frame in frames_of(audio):
        loop.feed(frame)


def test_full_turn_wake_listen_think_speak_idle():
    player = FakePlayer(frames_long=5)
    loop, states = make(player=player)
    feed(loop, quiet(30) + tone(900) + quiet(900) + quiet(300))
    assert states == ["listening", "thinking", "speaking", "idle"]
    assert loop.heard == ["what's on today"]
    assert player.started == [(200, 24_000)]


def test_one_breath_request_skips_listening():
    loop, states = make(wake=WakeOnFrame(request="remind me at nine"))
    feed(loop, quiet(30))
    assert states == ["thinking", "speaking"]
    assert loop.heard == ["remind me at nine"]


def test_listening_times_out_back_to_idle():
    loop, states = make()
    feed(loop, quiet(30) + quiet(6500))
    assert states == ["listening", "idle"]
    assert loop.heard == []


def test_barge_in_stops_speech_and_listens():
    player = FakePlayer(frames_long=1000)
    loop, states = make(stt=STT("what's on today", "stop, actually"), player=player)
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert loop.state == "speaking"
    feed(loop, tone(300, amplitude=12000))  # he talks over her
    assert player.stopped == 1
    assert states[-1] == "listening"
    feed(loop, tone(600) + quiet(900))
    assert loop.heard == ["what's on today", "stop, actually"]


def test_quiet_echo_does_not_barge_in():
    player = FakePlayer(frames_long=1000)
    loop, _ = make(player=player)
    feed(loop, quiet(30) + tone(900) + quiet(900))
    feed(loop, tone(1000, amplitude=800))  # her own voice leaking from the speakers
    assert player.stopped == 0 and loop.state == "speaking"


def test_thinking_error_still_answers():
    def broken(text):
        raise RuntimeError("ollama down")

    player = FakePlayer()
    loop, states = make(think=broken, player=player)
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert "speaking" in states and player.started


def test_empty_transcript_goes_back_to_idle():
    loop, states = make(stt=STT(""))
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert states == ["listening", "idle"]


def test_run_consumes_a_frame_source():
    loop, states = make()
    loop.run(frames_of(quiet(30) + tone(900) + quiet(900)))
    assert loop.heard == ["what's on today"]


def test_cli_voice_without_voice_extras_explains(tmp_path, monkeypatch, capsys):
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "sounddevice":
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["voice"]) == 1
    assert "[voice]" in capsys.readouterr().out


def test_wake_now_listens_without_the_wake_word():
    loop, states = make(wake=WakeOnFrame(at=10_000))
    loop.wake_now()
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert states[:2] == ["listening", "thinking"]
    assert loop.heard == ["what's on today"]


def test_wake_now_while_speaking_stops_her_and_listens():
    player = FakePlayer(frames_long=1000)
    loop, states = make(player=player)
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert loop.state == "speaking"
    loop.wake_now()
    feed(loop, quiet(30))
    assert loop.state == "listening"
    assert player.stopped == 1


def test_transcript_lines_are_reported():
    lines = []
    loop, _ = make()
    loop.on_transcript = lambda role, text: lines.append((role, text))
    feed(loop, quiet(30) + tone(900) + quiet(900))
    assert lines == [("you", "what's on today"), ("rosie", "reply to what's on today")]
