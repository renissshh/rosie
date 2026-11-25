"""Text-to-speech with sherpa-onnx (local, free, Apache-2.0), and Rosie's voice.

A few English voices are listed in VOICES; `rosie voices` shows them and
`rosie say "Good evening, VinsmokE" --voice kokoro-emma --out hi.wav` lets you
hear one. The chosen one goes in rosie.yaml as `voice:`. The default is a calm
British female voice (Kokoro "bf_emma"), to fit the butler persona in SOUL.md.

Models are downloaded once from the sherpa-onnx GitHub releases into
D:\\Rosie\\models and unpacked with tarfile's safe "data" filter (no files outside
the folder, no links). sherpa-onnx is optional: pip install -e ".[voice]".
"""

from __future__ import annotations

import tarfile
import tempfile
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"


@dataclass(frozen=True)
class Voice:
    name: str
    family: Literal["kokoro", "vits"]
    archive: str  # release asset name without .tar.bz2, also the unpacked folder name
    sid: int  # speaker id inside a multi-speaker model
    description: str
    model_file: str = "model.onnx"

    @property
    def url(self) -> str:
        return f"{RELEASES}{self.archive}.tar.bz2"


VOICES: dict[str, Voice] = {
    v.name: v
    for v in [
        Voice("kokoro-emma", "kokoro", "kokoro-en-v0_19", 7, "British female, calm (default)"),
        Voice("kokoro-isabella", "kokoro", "kokoro-en-v0_19", 8, "British female, brighter"),
        Voice("kokoro-bella", "kokoro", "kokoro-en-v0_19", 1, "American female, warm"),
        Voice("kokoro-george", "kokoro", "kokoro-en-v0_19", 9, "British male, butler-like"),
        Voice(
            "piper-alba",
            "vits",
            "vits-piper-en_GB-alba-medium",
            0,
            "British female, small and fast (for slow laptops)",
            "en_GB-alba-medium.onnx",
        ),
    ]
}
DEFAULT_VOICE = "kokoro-emma"


class TTSError(RuntimeError):
    """A voice could not be found, downloaded or loaded."""


def get_voice(name: str) -> Voice:
    try:
        return VOICES[name]
    except KeyError:
        raise TTSError(f"unknown voice '{name}'; try one of: {', '.join(VOICES)}") from None


def ensure_model(voice: Voice, models_dir: Path, http: httpx.Client | None = None) -> Path:
    """Download and unpack the voice's model once. Returns its folder."""
    folder = models_dir / voice.archive
    if (folder / voice.model_file).is_file():
        return folder
    models_dir.mkdir(parents=True, exist_ok=True)
    http = http or httpx.Client(timeout=600, follow_redirects=True)
    with tempfile.TemporaryDirectory(dir=models_dir) as tmp:
        archive = Path(tmp) / f"{voice.archive}.tar.bz2"
        try:
            with http.stream("GET", voice.url) as response:
                response.raise_for_status()
                with archive.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        except httpx.HTTPError as exc:
            raise TTSError(f"could not download {voice.archive}: {exc}") from exc
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(models_dir, filter="data")  # refuses paths outside models_dir
    if not (folder / voice.model_file).is_file():
        raise TTSError(f"{voice.archive} did not contain {voice.model_file}")
    return folder


def float_to_pcm(samples) -> bytes:
    """Floats in [-1, 1] -> int16 PCM, clipping anything louder."""
    return array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples)).tobytes()


def build_config(voice: Voice, folder: Path, sherpa: Any, threads: int = 2) -> Any:
    files = {"model": str(folder / voice.model_file), "tokens": str(folder / "tokens.txt")}
    espeak = str(folder / "espeak-ng-data")
    if voice.family == "kokoro":
        family = {
            "kokoro": sherpa.OfflineTtsKokoroModelConfig(
                voices=str(folder / "voices.bin"), data_dir=espeak, **files
            )
        }
    else:
        family = {"vits": sherpa.OfflineTtsVitsModelConfig(data_dir=espeak, **files)}
    model = sherpa.OfflineTtsModelConfig(num_threads=threads, provider="cpu", **family)
    return sherpa.OfflineTtsConfig(model=model, max_num_sentences=1)


class Speaker:
    """Turns text into PCM audio with the chosen voice."""

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        models_dir: Path = Path("models"),
        sherpa: Any = None,
        download: Callable[[Voice, Path], Path] = ensure_model,
    ) -> None:
        if sherpa is None:
            try:
                import sherpa_onnx as sherpa
            except ImportError as exc:
                raise TTSError(
                    'text-to-speech needs sherpa-onnx: pip install -e ".[voice]"'
                ) from exc
        self.voice = get_voice(voice)
        folder = download(self.voice, models_dir)
        self._tts = sherpa.OfflineTts(build_config(self.voice, folder, sherpa))

    def synthesize(self, text: str, speed: float = 1.0) -> tuple[bytes, int]:
        """Returns (16-bit PCM, sample rate). Kokoro is 24 kHz, Piper 22.05 kHz."""
        audio = self._tts.generate(text, sid=self.voice.sid, speed=speed)
        return float_to_pcm(audio.samples), audio.sample_rate
