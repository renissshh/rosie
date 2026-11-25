import builtins
import math
from array import array

import pytest

from rosie.audio import SAMPLE_RATE, frames_of
from rosie.stt import Transcript
from rosie.wakeword import OWW_SAMPLES, Cooldown, OpenWakeWord, SpokenName, strip_wake_phrase


def tone(ms, amplitude=6000):
    n = SAMPLE_RATE * ms // 1000
    return array(
        "h", (int(amplitude * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE)) for i in range(n))
    ).tobytes()


def quiet(ms):
    return b"\0\0" * (SAMPLE_RATE * ms // 1000)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize(
    "text, rest",
    [
        ("Hey Rosie, what's next?", "what's next?"),
        ("rosie remind me at nine", "remind me at nine"),
        ("Hey, Rosy.", ""),
        ("OK Rosey what time is it", "what time is it"),
        ("Rosiest day ever", None),
        ("I told Rosie", None),
        ("hello", None),
    ],
)
def test_strip_wake_phrase(text, rest):
    assert strip_wake_phrase(text) == rest


def test_cooldown():
    clock = Clock()
    cd = Cooldown(2, clock)
    assert cd.ready()
    cd.fire()
    clock.t = 1.9
    assert not cd.ready()
    clock.t = 2.0
    assert cd.ready()


class FakeOWW:
    def __init__(self, wakeword_models, inference_framework):
        self.models, self.chunks, self.scores = wakeword_models, [], []

    def predict(self, chunk):
        self.chunks.append(len(chunk))
        return {"hey_rosie": self.scores.pop(0) if self.scores else 0.0}


def test_openwakeword_chunks_threshold_and_cooldown():
    clock = Clock()
    oww = OpenWakeWord("hey_rosie.onnx", loader=FakeOWW, clock=clock)
    model = oww._model
    assert model.models == ["hey_rosie.onnx"]
    model.scores = [0.1, 0.9, 0.95]
    frames = list(frames_of(quiet(30 * 9)))  # 9 x 480 samples = 4320 -> 3 chunks of 1280
    woke = [oww.feed(f) for f in frames]
    assert model.chunks == [OWW_SAMPLES] * 3
    assert woke.count(True) == 1  # the 0.95 right after came within the cooldown
    clock.t = 5
    model.scores = [0.8]
    assert any(oww.feed(f) for f in frames_of(quiet(90)))


def test_openwakeword_stand_in_model_until_trained():
    assert OpenWakeWord(loader=FakeOWW)._model.models == ["hey_jarvis"]


def test_openwakeword_missing_package(monkeypatch):
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name.startswith("openwakeword"):
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match=r"\[voice\]"):
        OpenWakeWord()


class FakeSTT:
    def __init__(self, *texts):
        self.texts = list(texts)

    def transcribe(self, pcm):
        return Transcript(self.texts.pop(0), len(pcm) / 32000, 0.1)


def run(detector, audio):
    return [detector.feed(f) for f in frames_of(audio)].count(True)


def test_spoken_name_wakes_and_keeps_the_request():
    wake = SpokenName(FakeSTT("Hey Rosie, what's on today?"))
    assert run(wake, quiet(300) + tone(900) + quiet(900)) == 1
    assert wake.request == "what's on today?"


def test_spoken_name_ignores_other_speech():
    wake = SpokenName(FakeSTT("pass the salt"))
    assert run(wake, quiet(300) + tone(900) + quiet(900)) == 0


def test_spoken_name_alone_has_no_request():
    wake = SpokenName(FakeSTT("Rosie?"))
    assert run(wake, quiet(300) + tone(600) + quiet(900)) == 1
    assert wake.request is None
