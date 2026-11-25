"""Telegram voice notes <-> Rosie's 16-bit PCM.

Telegram voice notes are OGG files with the Opus codec. PyAV (FFmpeg bindings,
installed with faster-whisper) decodes them to 16 kHz mono PCM for speech-to-text,
and encodes Rosie's spoken replies back to OGG/Opus so they show up as a voice
bubble with a waveform, not as a file attachment.
"""

from __future__ import annotations

import io

from rosie.audio import SAMPLE_RATE


def _av():
    try:
        import av
    except ImportError as exc:
        raise RuntimeError('voice notes need PyAV: pip install -e ".[voice]"') from exc
    return av


def decode_to_pcm(data: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """Any audio file FFmpeg understands (OGG/Opus, MP3, M4A...) -> mono int16 PCM."""
    av = _av()
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks: list[bytes] = []
    with av.open(io.BytesIO(data)) as container:
        for frame in container.decode(audio=0):
            chunks += [f.to_ndarray().tobytes() for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().tobytes() for f in resampler.resample(None)]  # flush
    return b"".join(chunks)


def encode_ogg_opus(pcm: bytes, rate: int) -> bytes:
    """Mono int16 PCM at any rate -> an OGG/Opus voice note (Opus runs at 48 kHz)."""
    av = _av()
    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).reshape(1, -1)
    out_buffer = io.BytesIO()
    with av.open(out_buffer, "w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48_000)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):  # PyAV resamples and re-chunks for Opus
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return out_buffer.getvalue()
