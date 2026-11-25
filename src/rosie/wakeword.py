"""Wake word: "Hey Rosie".

Two detectors share one interface, `feed(frame) -> bool` (True = wake up):

- `OpenWakeWord`: a small always-on model (openWakeWord, Apache-2.0) scoring every
  80 ms of audio. It needs a model trained on "Hey Rosie": until you record samples
  (see docs/VOICE.md), the built-in "hey jarvis" model can stand in.
- `SpokenName`: the fallback that needs no training. Each utterance found by the VAD
  is transcribed and Rosie wakes if it starts with her name ("Hey Rosie, ...",
  "Rosie ..."). Heavier on the CPU, but works on day one, and the rest of the
  sentence becomes the request.

Both have a cooldown so one "Hey Rosie" doesn't trigger twice.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from rosie.audio import Utterance, UtteranceDetector
from rosie.stt import Transcriber

OWW_SAMPLES = 1280  # openWakeWord scores 80 ms chunks at 16 kHz
# Whisper spells the name in several ways; all count.
_NAME = re.compile(
    r"^\W*(?:(?:hey|hi|ok|okay|hello)[\s,]+)?(?:rosie|rosy|rozy|rosey|roosie)\b[\s,.!?]*",
    re.IGNORECASE,
)


def strip_wake_phrase(text: str) -> str | None:
    """'Hey Rosie, what's next?' -> "what's next?"; None if it doesn't start with her name."""
    match = _NAME.match(text)
    return None if match is None else text[match.end() :].strip()


class Cooldown:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds = seconds
        self._clock = clock
        self._last = float("-inf")

    def ready(self) -> bool:
        return self._clock() - self._last >= self.seconds

    def fire(self) -> None:
        self._last = self._clock()


class OpenWakeWord:
    def __init__(
        self,
        model_path: str | None = None,
        threshold: float = 0.5,
        cooldown_s: float = 2.0,
        loader: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if loader is None:
            try:
                from openwakeword.model import Model
            except ImportError as exc:
                raise RuntimeError(
                    'the wake word needs openwakeword: pip install -e ".[voice]"'
                ) from exc
            loader = Model
        models = [model_path] if model_path else ["hey_jarvis"]  # stand-in until trained
        self._model = loader(wakeword_models=models, inference_framework="onnx")
        self.threshold = threshold
        self._cooldown = Cooldown(cooldown_s, clock)
        self._buffer = b""

    def feed(self, frame: bytes) -> bool:
        """Buffer 30 ms frames into 80 ms chunks; True when any model scores high enough."""
        import numpy as np

        self._buffer += frame
        woke = False
        while len(self._buffer) >= OWW_SAMPLES * 2:
            chunk, self._buffer = self._buffer[: OWW_SAMPLES * 2], self._buffer[OWW_SAMPLES * 2 :]
            scores = self._model.predict(np.frombuffer(chunk, dtype=np.int16))
            if max(scores.values(), default=0.0) >= self.threshold and self._cooldown.ready():
                self._cooldown.fire()
                woke = True
        return woke


class SpokenName:
    """Wake by transcribing utterances and checking for Rosie's name."""

    def __init__(
        self,
        transcriber: Transcriber,
        detector: UtteranceDetector | None = None,
        cooldown_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transcriber = transcriber
        self.detector = detector or UtteranceDetector(end_silence_ms=600, max_seconds=8)
        self._cooldown = Cooldown(cooldown_s, clock)
        self.request: str | None = None  # words said after her name, if any

    def feed(self, frame: bytes) -> bool:
        utterance: Utterance | None = self.detector.feed(frame)
        if utterance is None or not self._cooldown.ready():
            return False
        rest = strip_wake_phrase(self.transcriber.transcribe(utterance.audio).text)
        if rest is None:
            return False
        self._cooldown.fire()
        self.request = rest or None
        return True
