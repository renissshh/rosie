"""Microphone capture and voice activity detection (VAD).

Audio everywhere in Rosie is 16 kHz, mono, 16-bit PCM, in 30 ms frames (480 samples),
which is what speech-to-text models expect.

    Microphone  -> frames -> EnergyVAD (speech or not?) -> UtteranceDetector -> one utterance

`EnergyVAD` is deliberately simple: a frame is speech if it is clearly louder than the
background noise, which it keeps learning (fast from quiet frames, slowly from loud
ones). `UtteranceDetector` turns
per-frame decisions into whole utterances: it starts after a few speech frames (so a
click doesn't count), keeps a little audio from before the start (so the first syllable
isn't cut), and ends after a pause. Both are pure Python and tested with synthetic audio.

`Microphone` needs the optional `sounddevice` package: pip install -e ".[voice]".
"""

from __future__ import annotations

import math
import queue
import wave
from array import array
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480
FRAME_BYTES = FRAME_SAMPLES * 2


def rms(frame: bytes) -> float:
    """Loudness of a 16-bit PCM frame (0 = silence, 32767 = full scale)."""
    samples = array("h", frame)
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EnergyVAD:
    """Speech = louder than `ratio` x the learned noise floor (and above a minimum)."""

    def __init__(
        self,
        ratio: float = 3.0,
        min_level: float = 300.0,
        adapt: float = 0.05,
        adapt_loud: float = 0.001,
    ) -> None:
        self.ratio = ratio
        self.min_level = min_level
        self.adapt = adapt
        # Loud frames also nudge the floor, very slowly: a steady fan is learned in a few
        # seconds, while a normal sentence barely moves it.
        self.adapt_loud = adapt_loud
        self.noise = min_level / ratio

    def is_speech(self, frame: bytes) -> bool:
        level = rms(frame)
        speech = level > max(self.min_level, self.noise * self.ratio)
        rate = self.adapt_loud if speech else self.adapt
        self.noise += rate * (level - self.noise)
        return speech


@dataclass(frozen=True)
class Utterance:
    audio: bytes  # 16 kHz mono int16 PCM

    @property
    def seconds(self) -> float:
        return len(self.audio) / 2 / SAMPLE_RATE


class UtteranceDetector:
    def __init__(
        self,
        vad: EnergyVAD | None = None,
        start_frames: int = 3,  # 90 ms of speech to start
        end_silence_ms: int = 800,  # pause that ends an utterance
        preroll_ms: int = 300,
        max_seconds: float = 15.0,
    ) -> None:
        self.vad = vad or EnergyVAD()
        self.start_frames = start_frames
        self.end_frames = end_silence_ms // FRAME_MS
        self.max_frames = int(max_seconds * 1000 // FRAME_MS)
        self._preroll: deque[bytes] = deque(maxlen=preroll_ms // FRAME_MS)
        self._reset()

    def _reset(self) -> None:
        self._speaking = False
        self._run = 0  # consecutive speech frames while waiting
        self._silence = 0
        self._frames: list[bytes] = []

    def feed(self, frame: bytes) -> Utterance | None:
        """Feed one frame; returns an Utterance when one has just ended."""
        speech = self.vad.is_speech(frame)
        if not self._speaking:
            self._preroll.append(frame)
            self._run = self._run + 1 if speech else 0
            if self._run >= self.start_frames:
                self._speaking = True
                self._frames = list(self._preroll)
                self._preroll.clear()
            return None
        self._frames.append(frame)
        self._silence = 0 if speech else self._silence + 1
        if self._silence >= self.end_frames or len(self._frames) >= self.max_frames:
            # drop most of the trailing silence, keep a short tail
            keep = len(self._frames) - max(0, self._silence - 3)
            utterance = Utterance(b"".join(self._frames[:keep]))
            self._reset()
            return utterance
        return None

    def utterances(self, frames: Iterable[bytes]) -> Iterator[Utterance]:
        for frame in frames:
            if (utterance := self.feed(frame)) is not None:
                yield utterance


def frames_of(pcm: bytes) -> Iterator[bytes]:
    """Split PCM into whole 30 ms frames (a partial last frame is dropped)."""
    for start in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
        yield pcm[start : start + FRAME_BYTES]


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(f"{path} must be 16 kHz mono 16-bit WAV")
        return w.readframes(w.getnframes())


class Microphone:
    """Default input device as a stream of 30 ms frames (needs `sounddevice`)."""

    def __init__(self, device: int | str | None = None) -> None:
        try:
            import sounddevice
        except ImportError as exc:  # optional dependency
            raise RuntimeError('voice needs sounddevice: pip install -e ".[voice]"') from exc
        self._sd = sounddevice
        self.device = device
        self._queue: queue.Queue[bytes] = queue.Queue()

    def frames(self) -> Iterator[bytes]:
        def callback(data, n_frames, time_info, status):  # runs on the audio thread
            self._queue.put(bytes(data))

        with self._sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_SAMPLES,
            channels=1,
            dtype="int16",
            device=self.device,
            callback=callback,
        ):
            while True:
                yield self._queue.get()


def play(pcm: bytes, rate: int) -> None:
    """Play 16-bit mono PCM on the default speakers and wait until it finishes."""
    try:
        import numpy as np
        import sounddevice
    except ImportError as exc:
        raise RuntimeError('playback needs sounddevice: pip install -e ".[voice]"') from exc
    sounddevice.play(np.frombuffer(pcm, dtype=np.int16), rate, blocking=True)
