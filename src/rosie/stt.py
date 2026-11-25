"""Speech-to-text with faster-whisper (local, free), plus a latency benchmark.

    Utterance (16 kHz PCM) -> WhisperTranscriber -> Transcript("remind me at nine", ...)

Settings chosen for latency on a CPU laptop: int8 weights, beam size 1, English by
default (Whisper's ".en" models are smaller and more accurate for English). Models are
downloaded once into D:\\Rosie\\models.

The benchmark answers "is it fast enough to feel like a conversation?": for each
recorded sample it measures how long transcription took, the real-time factor
(time taken / audio length, below 1 means faster than real time) and the word error
rate against the expected text.

faster-whisper is optional: pip install -e ".[voice]".
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rosie.audio import SAMPLE_RATE, read_wav

DEFAULT_MODEL = "base.en"


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_s: float
    took_s: float
    language: str = "en"

    @property
    def rtf(self) -> float:
        """Real-time factor: below 1.0 is faster than real time."""
        return self.took_s / self.audio_s if self.audio_s else 0.0


class Transcriber(Protocol):
    def transcribe(self, pcm: bytes) -> Transcript: ...


def pcm_to_float(pcm: bytes):
    """int16 PCM -> float32 numpy array in [-1, 1], the input Whisper models expect."""
    import numpy as np  # installed with faster-whisper

    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class WhisperTranscriber:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        models_dir: Path | None = None,
        language: str | None = "en",
        loader: Callable[..., object] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if loader is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    'speech-to-text needs faster-whisper: pip install -e ".[voice]"'
                ) from exc
            loader = WhisperModel
        self.model_name = model
        self.language = language
        self._clock = clock
        root = str(models_dir) if models_dir else None
        self._model = loader(model, device="cpu", compute_type="int8", download_root=root)

    def transcribe(self, pcm: bytes) -> Transcript:
        audio = pcm_to_float(pcm)
        start = self._clock()
        segments, info = self._model.transcribe(  # type: ignore[attr-defined]
            audio, language=self.language, beam_size=1, condition_on_previous_text=False
        )
        text = " ".join(s.text.strip() for s in segments).strip()  # generator: runs here
        took = self._clock() - start
        return Transcript(text, len(pcm) / 2 / SAMPLE_RATE, took, info.language)


# ---- benchmark -------------------------------------------------------------
_WORDS = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def word_error_rate(expected: str, got: str) -> float:
    """(substitutions + deletions + insertions) / words expected, by edit distance."""
    ref, hyp = words(expected), words(got)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


@dataclass(frozen=True)
class BenchResult:
    name: str
    expected: str
    transcript: Transcript

    @property
    def wer(self) -> float:
        return word_error_rate(self.expected, self.transcript.text)


def load_samples(folder: Path) -> list[tuple[str, bytes, str]]:
    """Every `name.wav` with a `name.txt` next to it (the expected words)."""
    samples = []
    for wav in sorted(folder.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        if txt.is_file():
            samples.append((wav.stem, read_wav(wav), txt.read_text(encoding="utf-8").strip()))
    return samples


def benchmark(transcriber: Transcriber, samples: Iterable[tuple[str, bytes, str]]):
    return [
        BenchResult(name, expected, transcriber.transcribe(pcm)) for name, pcm, expected in samples
    ]


def report(results: list[BenchResult], model: str) -> str:
    if not results:
        return "No samples: put name.wav + name.txt pairs in the folder."
    lines = [
        f"# Speech-to-text benchmark ({model})",
        "",
        "| Sample | Audio s | Took s | RTF | WER | Heard |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        t = r.transcript
        numbers = f"{t.audio_s:.1f} | {t.took_s:.2f} | {t.rtf:.2f} | {r.wer:.0%}"
        lines.append(f"| {r.name} | {numbers} | {t.text} |")
    n = len(results)
    avg_took = sum(r.transcript.took_s for r in results) / n
    avg_rtf = sum(r.transcript.rtf for r in results) / n
    avg_wer = sum(r.wer for r in results) / n
    verdict = "fast enough to feel conversational" if avg_took < 1.5 else "try a smaller model"
    lines += [
        "",
        f"Average: {avg_took:.2f} s per utterance, RTF {avg_rtf:.2f}, WER {avg_wer:.0%}"
        f" -> {verdict}.",
    ]
    return "\n".join(lines) + "\n"
