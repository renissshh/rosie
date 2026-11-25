import math
from array import array

import pytest

pytest.importorskip("av")

from rosie.voice_notes import decode_to_pcm, encode_ogg_opus  # noqa: E402


def tone(rate, seconds=1.0, amplitude=8000):
    n = int(rate * seconds)
    return array(
        "h", (int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n))
    ).tobytes()


@pytest.mark.parametrize("rate", [24_000, 22_050, 16_000])
def test_round_trip_through_ogg_opus(rate):
    ogg = encode_ogg_opus(tone(rate), rate)
    assert ogg[:4] == b"OggS"
    pcm = decode_to_pcm(ogg)
    seconds = len(pcm) / 2 / 16_000
    assert 0.9 <= seconds <= 1.2  # same length, now 16 kHz for speech-to-text
    samples = array("h", pcm)
    assert max(abs(s) for s in samples) > 2000  # still a loud tone, not silence


def test_garbage_is_an_error():
    with pytest.raises(Exception):  # noqa: B017 (PyAV raises its own error types)
        decode_to_pcm(b"not audio at all")
