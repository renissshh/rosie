"""The hands-free loop: wake -> listen -> think -> speak, with barge-in.

    idle ──"Hey Rosie"──> listening ──utterance──> thinking ──reply──> speaking ──done──> idle
      ^                       │ 6 s of nothing                          │ you talk over her
      └───────────────────────┘                                         └──> listening

It is a state machine fed one 30 ms microphone frame at a time (`feed`), so it is
tested with recorded or synthetic audio and no real microphone. Every state change
is reported through `on_state`, which the orb UI uses for its look, and every line of
the conversation through `on_transcript`, which the Command Deck shows live.
`wake_now()` starts listening without the wake word (a click on the orb, Ctrl+Space).

Barge-in: while Rosie speaks, the microphone keeps listening. If you talk for about a
fifth of a second she stops mid-sentence and listens. Speakers leak into the mic, so
during speech the VAD needs a louder signal (`barge_in_ratio`); headphones work best.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, Protocol

from rosie.audio import FRAME_MS, EnergyVAD, UtteranceDetector
from rosie.stt import Transcriber

log = logging.getLogger("rosie.voice")

State = Literal["idle", "listening", "thinking", "speaking"]


class WakeDetector(Protocol):
    def feed(self, frame: bytes) -> bool: ...


class Player(Protocol):
    def start(self, pcm: bytes, rate: int) -> None: ...
    def is_playing(self) -> bool: ...
    def stop(self) -> None: ...


class SoundDevicePlayer:
    """Non-blocking playback on the default speakers (optional sounddevice)."""

    def __init__(self) -> None:
        import numpy as np
        import sounddevice

        self._np, self._sd = np, sounddevice

    def start(self, pcm: bytes, rate: int) -> None:
        self._sd.play(self._np.frombuffer(pcm, dtype=self._np.int16), rate)

    def is_playing(self) -> bool:
        stream = self._sd.get_stream()
        return bool(stream and stream.active)

    def stop(self) -> None:
        self._sd.stop()


class VoiceLoop:
    def __init__(
        self,
        wake: WakeDetector,
        transcriber: Transcriber,
        think: Callable[[str], str],
        synthesize: Callable[[str], tuple[bytes, int]],
        player: Player,
        on_state: Callable[[State], None] = lambda state: None,
        on_transcript: Callable[[str, str], None] = lambda role, text: None,
        listen_timeout_s: float = 6.0,
        barge_in_frames: int = 6,  # ~180 ms of speech
        barge_in_ratio: float = 6.0,
    ) -> None:
        self.wake = wake
        self.transcriber = transcriber
        self.think = think
        self.synthesize = synthesize
        self.player = player
        self.on_state = on_state
        self.on_transcript = on_transcript
        self._wake_requested = False
        self.listen_timeout_frames = int(listen_timeout_s * 1000 // FRAME_MS)
        self.barge_in_frames = barge_in_frames
        self._barge_vad = EnergyVAD(ratio=barge_in_ratio, min_level=1500)
        self.state: State = "idle"
        self._listener = UtteranceDetector()
        self._waited = 0
        self._loud = 0
        self.heard: list[str] = []  # transcript of this session, for logs and tests

    def _set(self, state: State) -> None:
        if state != self.state:
            log.info("voice: %s -> %s", self.state, state)
            self.state = state
            self.on_state(state)

    def _listen(self) -> None:
        self._listener = UtteranceDetector()
        self._waited = 0
        self._set("listening")

    def wake_now(self) -> None:
        """Listen from the next frame on, as if the wake word was heard. Thread-safe:
        it only sets a flag that the microphone thread picks up."""
        self._wake_requested = True

    def feed(self, frame: bytes) -> None:
        if self._wake_requested:
            self._wake_requested = False
            if self.state in ("idle", "speaking"):
                if self.state == "speaking":
                    self.player.stop()
                self._listen()
                return
        if self.state == "idle":
            if self.wake.feed(frame):
                request = getattr(self.wake, "request", None)
                if request:  # "Hey Rosie, what's next?" in one breath
                    self.wake.request = None  # type: ignore[attr-defined]
                    self._respond(request)
                else:
                    self._listen()
        elif self.state == "listening":
            utterance = self._listener.feed(frame)
            if utterance is not None:
                text = self.transcriber.transcribe(utterance.audio).text.strip()
                if text:
                    self._respond(text)
                else:
                    self._set("idle")
            else:
                self._waited += 1
                if self._waited >= self.listen_timeout_frames and not self._listener.in_utterance:
                    self._set("idle")  # woke by mistake, or he changed his mind
        elif self.state == "speaking":
            self._speaking_frame(frame)

    def _respond(self, text: str) -> None:
        self.heard.append(text)
        self.on_transcript("you", text)
        self._set("thinking")
        try:
            reply = self.think(text)
        except Exception:
            log.exception("thinking failed")
            reply = "Sorry, something went wrong on my side."
        self.on_transcript("rosie", reply)
        pcm, rate = self.synthesize(reply)
        self._loud = 0
        self.player.start(pcm, rate)
        self._set("speaking")

    def _speaking_frame(self, frame: bytes) -> None:
        if not self.player.is_playing():
            self._set("idle")
            return
        self._loud = self._loud + 1 if self._barge_vad.is_speech(frame) else 0
        if self._loud >= self.barge_in_frames:
            self.player.stop()
            log.info("barge-in: stopped speaking")
            self._listen()

    def run(self, frames) -> None:
        """Feed frames from a source (e.g. Microphone().frames()) until it ends."""
        for frame in frames:
            self.feed(frame)
