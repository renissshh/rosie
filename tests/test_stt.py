import builtins
from types import SimpleNamespace

import pytest

import rosie.stt
from rosie.__main__ import main
from rosie.audio import SAMPLE_RATE, write_wav
from rosie.stt import (
    BenchResult,
    Transcript,
    WhisperTranscriber,
    benchmark,
    load_samples,
    pcm_to_float,
    report,
    word_error_rate,
)

ONE_SECOND = b"\0\0" * SAMPLE_RATE


class FakeModel:
    """Plays faster_whisper.WhisperModel: records settings, returns fixed segments."""

    def __init__(self, name, **kwargs):
        self.name, self.kwargs, self.calls = name, kwargs, []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        segments = (SimpleNamespace(text=t) for t in [" Remind me", " at nine. "])
        return segments, SimpleNamespace(language="en")


class Ticks:
    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


def test_pcm_to_float():
    values = pcm_to_float(b"\x00\x80\xff\x7f\x00\x00")
    assert values.dtype.name == "float32"
    assert values.tolist() == pytest.approx([-1.0, 32767 / 32768, 0.0])


def test_whisper_settings_and_transcript(tmp_path):
    stt = WhisperTranscriber("base.en", tmp_path, loader=FakeModel, clock=Ticks(10.0, 10.4))
    model = stt._model
    assert model.name == "base.en"
    assert model.kwargs == {"device": "cpu", "compute_type": "int8", "download_root": str(tmp_path)}
    result = stt.transcribe(ONE_SECOND * 2)
    assert result == Transcript("Remind me at nine.", 2.0, pytest.approx(0.4), "en")
    assert result.rtf == pytest.approx(0.2)
    audio, kwargs = model.calls[0]
    assert audio.dtype.name == "float32" and len(audio) == 2 * SAMPLE_RATE
    assert kwargs["beam_size"] == 1 and kwargs["language"] == "en"


def test_missing_faster_whisper_explains(monkeypatch):
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "faster_whisper":
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match=r"\[voice\]"):
        WhisperTranscriber()


@pytest.mark.parametrize(
    "expected, got, wer",
    [
        ("remind me at nine", "Remind me at nine.", 0.0),
        ("remind me at nine", "remind me at five", 0.25),
        ("remind me at nine", "remind me", 0.5),
        ("remind me", "please remind me now", 1.0),
        ("", "", 0.0),
        ("", "noise", 1.0),
    ],
)
def test_word_error_rate(expected, got, wer):
    assert word_error_rate(expected, got) == pytest.approx(wer)


def test_benchmark_from_a_folder(tmp_path):
    write_wav(tmp_path / "a.wav", ONE_SECOND)
    (tmp_path / "a.txt").write_text("remind me at nine", encoding="utf-8")
    write_wav(tmp_path / "no_text.wav", ONE_SECOND)  # skipped: no expected text

    class Fake:
        def transcribe(self, pcm):
            return Transcript("remind me at five", len(pcm) / 2 / SAMPLE_RATE, 0.5)

    samples = load_samples(tmp_path)
    assert [s[0] for s in samples] == ["a"]
    results = benchmark(Fake(), samples)
    assert results[0].wer == 0.25
    text = report(results, "base.en")
    assert "| a | 1.0 | 0.50 | 0.50 | 25% | remind me at five |" in text
    assert "fast enough" in text


def test_report_slow_and_empty():
    slow = BenchResult("x", "hi", Transcript("hi", 2.0, 3.0))
    assert "try a smaller model" in report([slow], "small")
    assert "No samples" in report([], "base.en")


def test_cli_without_faster_whisper(tmp_path, monkeypatch, capsys):
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "faster_whisper":
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["stt-bench", str(tmp_path)]) == 1
    assert "faster-whisper" in capsys.readouterr().out


def test_cli_bench_writes_report(tmp_path, monkeypatch, capsys):
    class FakeWhisper:
        def __init__(self, model, models_dir):
            assert models_dir == tmp_path / "Rosie" / "models"

        def transcribe(self, pcm):
            return Transcript("hello rosie", 1.0, 0.3)

    write_wav(tmp_path / "s" / "hi.wav", ONE_SECOND)
    (tmp_path / "s" / "hi.txt").write_text("hello rosie", encoding="utf-8")
    monkeypatch.setattr(rosie.stt, "WhisperTranscriber", FakeWhisper)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["stt-bench", str(tmp_path / "s")]) == 0
    saved = (tmp_path / "Rosie" / "logs" / "stt-bench.md").read_text(encoding="utf-8")
    assert "| hi | 1.0 | 0.30 | 0.30 | 0% | hello rosie |" in saved
