import builtins
import io
import tarfile
import wave
from types import SimpleNamespace

import httpx
import pytest

import rosie.tts
from rosie.__main__ import main
from rosie.audio import write_wav
from rosie.tts import (
    DEFAULT_VOICE,
    VOICES,
    Speaker,
    TTSError,
    build_config,
    ensure_model,
    float_to_pcm,
    get_voice,
)


def tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def client(body: bytes, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


class FakeSherpa:
    """Records the config objects sherpa_onnx would receive."""

    def __init__(self):
        self.generated = []
        outer = self

        class OfflineTts:
            def __init__(self, config):
                outer.config = config

            def generate(self, text, sid=0, speed=1.0):
                outer.generated.append((text, sid, speed))
                return SimpleNamespace(samples=[0.0, 0.5, -1.5], sample_rate=24_000)

        self.OfflineTts = OfflineTts

    @staticmethod
    def OfflineTtsKokoroModelConfig(**kw):
        return ("kokoro", kw)

    @staticmethod
    def OfflineTtsVitsModelConfig(**kw):
        return ("vits", kw)

    @staticmethod
    def OfflineTtsModelConfig(**kw):
        return ("model", kw)

    @staticmethod
    def OfflineTtsConfig(**kw):
        return ("config", kw)


def test_catalog():
    assert DEFAULT_VOICE in VOICES
    assert get_voice("kokoro-george").sid == 9
    assert VOICES["piper-alba"].url.endswith("tts-models/vits-piper-en_GB-alba-medium.tar.bz2")
    with pytest.raises(TTSError, match="kokoro-emma"):
        get_voice("jarvis")


def test_float_to_pcm_clips():
    assert float_to_pcm([0.0, 1.0, -2.0]) == b"\x00\x00\xff\x7f\x01\x80"


def test_download_once_and_unpack(tmp_path):
    voice = VOICES["kokoro-emma"]
    body = tarball({"kokoro-en-v0_19/model.onnx": b"m", "kokoro-en-v0_19/tokens.txt": b"t"})
    seen = []
    folder = ensure_model(voice, tmp_path, client(body, seen=seen))
    assert (folder / "model.onnx").read_bytes() == b"m"
    assert ensure_model(voice, tmp_path, client(b"", status=500)) == folder  # cached
    assert seen == [voice.url]
    assert [p.name for p in tmp_path.iterdir()] == ["kokoro-en-v0_19"]  # temp files gone


def test_archive_cannot_write_outside_models_dir(tmp_path):
    models = tmp_path / "models"
    body = tarball({"../evil.txt": b"x", "kokoro-en-v0_19/model.onnx": b"m"})
    with pytest.raises(tarfile.TarError):
        ensure_model(VOICES["kokoro-emma"], models, client(body))
    assert not (tmp_path / "evil.txt").exists()


def test_download_errors(tmp_path):
    with pytest.raises(TTSError, match="could not download"):
        ensure_model(VOICES["kokoro-emma"], tmp_path, client(b"", status=404))
    with pytest.raises(TTSError, match="did not contain"):
        ensure_model(VOICES["kokoro-emma"], tmp_path, client(tarball({"other/x": b"1"})))


def test_kokoro_and_vits_configs(tmp_path):
    sherpa = FakeSherpa()
    config = build_config(VOICES["kokoro-emma"], tmp_path, sherpa)
    _, model = config[1]["model"]
    assert model["provider"] == "cpu" and model["num_threads"] == 2
    family, files = model["kokoro"]
    assert files["voices"].endswith("voices.bin") and files["data_dir"].endswith("espeak-ng-data")
    _, vits = build_config(VOICES["piper-alba"], tmp_path, sherpa)[1]["model"]
    assert vits["vits"][1]["model"].endswith("en_GB-alba-medium.onnx")


def test_speaker_uses_the_voice_speaker_id(tmp_path):
    sherpa = FakeSherpa()
    speaker = Speaker("kokoro-george", tmp_path, sherpa, download=lambda v, d: d / v.archive)
    pcm, rate = speaker.synthesize("Good evening, VinsmokE.", speed=1.1)
    assert rate == 24_000 and len(pcm) == 6
    assert sherpa.generated == [("Good evening, VinsmokE.", 9, 1.1)]


def test_missing_sherpa_explains(monkeypatch, tmp_path):
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "sherpa_onnx":
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(TTSError, match=r"\[voice\]"):
        Speaker(models_dir=tmp_path)


def test_wav_at_model_rate(tmp_path):
    path = write_wav(tmp_path / "hi.wav", b"\0\0" * 24_000, rate=24_000)
    with wave.open(str(path)) as w:
        assert w.getframerate() == 24_000 and w.getnframes() == 24_000


def test_cli_voices_marks_the_configured_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["voices"]) == 0
    out = capsys.readouterr().out
    assert "* kokoro-emma" in out and "  kokoro-george" in out


def test_cli_say_saves_wav(tmp_path, monkeypatch, capsys):
    class FakeSpeaker:
        def __init__(self, voice, models_dir):
            get_voice(voice)  # like the real one: unknown names raise TTSError

        def synthesize(self, text):
            return b"\0\0" * 100, 24_000

    monkeypatch.setattr(rosie.tts, "Speaker", FakeSpeaker)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["say", "hi", "--voice", "kokoro-george", "--out", "hi.wav"]) == 0
    assert (tmp_path / "hi.wav").is_file()
    assert main(["say", "hi", "--voice", "jarvis", "--out", "x.wav"]) == 1
