# Rosie's voice pipeline

```text
mic (30 ms frames) -> wake word -> VAD utterance -> faster-whisper -> agent -> sherpa-onnx -> speakers
   rosie.audio        rosie.wakeword  rosie.audio      rosie.stt               rosie.tts
```

Install once: `.venv\Scripts\python -m pip install -e ".[voice]"`, then run
`.venv\Scripts\rosie voice` and say "Hey Rosie, what's on today?".

Talk over her and she stops and listens (barge-in). Headphones help: with speakers, her
own voice reaches the mic, so barge-in needs you to speak up a little.

## "Hey Rosie" wake word

Rosie can wake two ways:

1. **Spoken name (works today, no training).** Every short utterance is transcribed;
   if it starts with "Hey Rosie" / "Rosie", she wakes and treats the rest of the
   sentence as the request. Uses more CPU while listening.
2. **openWakeWord model (light, always on).** Needs a model trained on "Hey Rosie".
   Until then the built-in "hey jarvis" model can stand in.

### Training "Hey Rosie" (after exams, about an hour, mostly waiting)

1. Record about 20 clips of yourself saying "Hey Rosie" (different distances, tones,
   with the fan on and off): 16 kHz mono WAV, 1 to 2 s each, into `D:\Rosie\samples\wake`.
2. Use openWakeWord's training notebook (see its README, "Training New Models"). It
   generates thousands of synthetic "Hey Rosie" clips and uses yours to check accuracy.
3. Put the resulting `hey_rosie.onnx` in `D:\Rosie\models\` and tell the next build night;
   Rosie switches from the spoken-name fallback to the model.

## Speech-to-text benchmark

See `docs/SETUP-WINDOWS.md` step 6 (`rosie stt-bench`).

## Choosing the voice

`rosie voices` lists them, `rosie say "text" --voice NAME` plays one, and `voice:` in
`config\rosie.yaml` keeps your choice.
