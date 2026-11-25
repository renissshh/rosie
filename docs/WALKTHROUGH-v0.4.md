# v0.4 walkthrough: "hands-free"

Sprint 4 gives Rosie ears and a voice, all local and free. Builds on
[v0.3](WALKTHROUGH-v0.3.md). Setup: `pip install -e ".[voice]"`, then `rosie voice`.
Full guide: [VOICE.md](VOICE.md).

## What works

```text
> rosie voice
Say "Hey Rosie". Ctrl+C to stop.
                     you: "Hey Rosie, what's on today?"
[thinking]
[speaking]           Rosie: "Two things: revise normal forms, and gym at six."
[idle]
```

- Wake by name ("Hey Rosie, ...") with no training, or with an openWakeWord model later
- Talk over her and she stops and listens (barge-in)
- Telegram voice notes: she transcribes yours and answers with a voice note of her own
- `rosie voices` / `rosie say` to pick her voice; `rosie stt-bench` to measure speed

## The pipeline

```text
mic 30 ms frames
  -> wake word   (rosie.wakeword: openWakeWord, or spoken-name fallback)
  -> utterance   (rosie.audio: EnergyVAD + UtteranceDetector, 800 ms pause ends it)
  -> text        (rosie.stt: faster-whisper base.en, int8, beam 1)
  -> reply       (the same agent, gate and memory as chat and Telegram)
  -> speech      (rosie.tts: sherpa-onnx Kokoro, "kokoro-emma")
  -> speakers    (rosie.voice_loop: barge-in while playing)
```

## Design decisions worth explaining

| Decision | Why |
| --- | --- |
| A state machine fed one frame at a time | The whole loop is tested with synthetic audio; no microphone, threads or sleeps in tests |
| Energy VAD with a learning noise floor | Pure Python and explainable; a fan becomes background in seconds. Silero VAD can replace it behind the same `is_speech` |
| Spoken-name wake fallback | Works on day one; the trained wake-word model is an upgrade, not a blocker |
| Louder threshold for barge-in | Her own voice leaks from the speakers into the mic; no echo cancellation yet |
| Voice extras optional | Chat, Telegram and CI never need audio libraries; every voice entry point explains how to install them |
| Safe model unpacking | Downloaded archives go through tarfile's "data" filter: no paths outside the models folder |

## Needs you (after exams, optional)

- `pip install -e ".[voice]"`, try `rosie say` with each voice, keep one in `rosie.yaml`
- Record a few sentences and run `rosie stt-bench` (is `base.en` fast enough?)
- Record about 20 "Hey Rosie" clips for the wake-word model (docs/VOICE.md)

## Numbers

- 354 tests on Ubuntu and Windows (the OGG/Opus codec round trip runs on both)
