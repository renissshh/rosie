# Credits

Rosie's own code is MIT. Code is only copied from MIT or Apache-2.0 projects, and every
copy is listed here with its source. Projects below that are marked "design reference"
contributed ideas, not code.

| Project | License | How Rosie uses it |
| --- | --- | --- |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) | MIT | Design reference: `SOUL.md` persona file, file-based memory |
| [OpenClaw](https://github.com/openclaw/openclaw) | MIT | Design reference: gateway daemon, chat allowlist pairing |
| [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) | Apache-2.0 | Design reference: morning digest flow |
| [Khoj](https://github.com/khoj-ai/khoj) | see repo | Design reference: search over an Obsidian vault |
| [Athena](https://github.com/Hamzacross/Athena), [Yumii](https://github.com/CodeNeuron58/Yumii) | see repos | Design reference: orb UI states, Python-to-Tauri bridge |
| [openWakeWord](https://github.com/dscripka/openWakeWord) | Apache-2.0 | Dependency (optional, `[voice]`): wake word |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Dependency (optional, `[voice]`): speech-to-text |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 | Dependency (optional, `[voice]`): text-to-speech |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | Dependency (optional, `[voice]`): microphone capture |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via sherpa-onnx | Apache-2.0 | Voice model (downloaded at runtime, not in the repo) |
| Piper voices via sherpa-onnx | see the model's folder | Optional small voice (downloaded at runtime, not in the repo) |
