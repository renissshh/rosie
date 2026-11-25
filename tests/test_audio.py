import builtins
import math
import random
import wave
from array import array

import pytest

from rosie.audio import (
    FRAME_BYTES,
    FRAME_MS,
    SAMPLE_RATE,
    EnergyVAD,
    Microphone,
    UtteranceDetector,
    frames_of,
    read_wav,
    rms,
    write_wav,
)

rng = random.Random(42)


def noise(ms, level=60):
    n = SAMPLE_RATE * ms // 1000
    return array("h", (int(rng.gauss(0, level)) for _ in range(n))).tobytes()


def tone(ms, amplitude=6000, hz=220):
    n = SAMPLE_RATE * ms // 1000
    samples = (int(amplitude * math.sin(2 * math.pi * hz * i / SAMPLE_RATE)) for i in range(n))
    return array("h", samples).tobytes()


def seconds(pcm):
    return len(pcm) / 2 / SAMPLE_RATE


def test_rms():
    assert rms(b"") == 0
    assert rms(array("h", [0] * 480).tobytes()) == 0
    assert rms(tone(30, 1000)) == pytest.approx(1000 / math.sqrt(2), rel=0.05)


def test_vad_separates_speech_from_room_noise():
    vad = EnergyVAD()
    for frame in frames_of(noise(1000)):
        assert not vad.is_speech(frame)
    assert vad.is_speech(next(frames_of(tone(30))))


def test_vad_adapts_to_a_noisy_room():
    vad = EnergyVAD()
    fan = noise(6000, level=400)  # loud fan: above min_level, should become "background"
    decisions = [vad.is_speech(f) for f in frames_of(fan)]
    assert not any(decisions[-20:])


def test_one_utterance_with_preroll_and_trailing_silence_trimmed():
    audio = noise(1000) + tone(1200) + noise(1500)
    found = list(UtteranceDetector().utterances(frames_of(audio)))
    assert len(found) == 1
    # 1.2 s of speech + up to 0.3 s pre-roll + a short tail, not the whole 1.5 s of silence
    assert 1.2 <= found[0].seconds <= 1.7


def test_short_click_is_ignored():
    audio = noise(510) + tone(45) + noise(1500)  # at most 2 frames < start_frames
    assert list(UtteranceDetector().utterances(frames_of(audio))) == []


def test_two_utterances_split_by_a_pause():
    audio = noise(500) + tone(800) + noise(1200) + tone(600, hz=330) + noise(1200)
    assert len(list(UtteranceDetector().utterances(frames_of(audio)))) == 2


def test_short_pause_inside_a_sentence_does_not_split():
    audio = noise(500) + tone(600) + noise(300) + tone(600) + noise(1200)
    found = list(UtteranceDetector().utterances(frames_of(audio)))
    assert len(found) == 1 and found[0].seconds >= 1.5


def test_max_length_cuts_endless_speech():
    detector = UtteranceDetector(max_seconds=2)
    found = list(detector.utterances(frames_of(noise(300) + tone(5000))))
    assert found and all(u.seconds <= 2.0 + FRAME_MS / 1000 for u in found)


def test_frames_of_drops_partial_frame():
    frames = list(frames_of(b"\0" * (FRAME_BYTES * 2 + 10)))
    assert len(frames) == 2 and all(len(f) == FRAME_BYTES for f in frames)


def test_wav_round_trip(tmp_path):
    pcm = tone(500)
    assert read_wav(write_wav(tmp_path / "a" / "u.wav", pcm)) == pcm
    assert seconds(pcm) == 0.5


def test_wav_wrong_format_rejected(tmp_path):
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44_100)
        w.writeframes(b"\0" * 400)
    with pytest.raises(ValueError, match="16 kHz mono"):
        read_wav(path)


def test_microphone_without_sounddevice_explains(monkeypatch):
    real_import = builtins.__import__

    def no_sounddevice(name, *args, **kwargs):
        if name == "sounddevice":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sounddevice)
    with pytest.raises(RuntimeError, match=r"\[voice\]"):
        Microphone()
