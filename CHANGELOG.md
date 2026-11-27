# Changelog

One section per release tag. `python scripts/release.py check` refuses to tag a
version that has no section here. Details for each release are in its walkthrough.

## Unreleased (toward v1.0)

- Study coach: timed sessions, weak-subject report, quizzes from your own notes ([COACHES.md](docs/COACHES.md)).
- Training coach: "bench 3x8 at 40 kg" logging (spoken numbers too), progression, stall alerts.
- Both coaches add a Coach section to the morning brief.
- Always-on server option: `rosie server`, Dockerfile, docker-compose with Ollama,
  rosie-vault shared through git ([SERVER.md](docs/SERVER.md)).
- Hardening: daily vault zip backups (last 14), rate limits, core watchdog ([RELIABILITY.md](docs/RELIABILITY.md)).
- `scripts/install-windows.ps1`, [user guide](docs/USER-GUIDE.md), demo GIF from the real orb.
- Browser end-to-end tests of core + orb page ([TESTING.md](docs/TESTING.md)).
- `scripts/release.py`: one version in every file, and a checklist before tagging.
- CI tags every sprint merge on `main` (`.github/workflows/tag.yml`), including v0.1 to v0.5.

## v0.5 "opens at login" (2026-11-27)

- Tauri 2 + React orb: transparent, always on top, bottom-right above the taskbar.
- WebSocket bridge to the core (`rosie serve`, 127.0.0.1:8765, origin-checked).
- Orb looks: offline, idle, listening, thinking, speaking, nudge, focus, unwell.
- Day Ring: today's blocks as a 24-hour clock, reminder dots, focus during study.
- Command Deck: Allow/Deny for the safety gate, Top 3, Now/Next, streak, countdown,
  transcript, text box, quick log.
- Tray, Ctrl+Space, single instance, start at login, health check on the orb.
- [Walkthrough](docs/WALKTHROUGH-v0.5.md).

## v0.4 "hands-free" (2026-11-26)

- Mic capture with voice activity detection; faster-whisper speech-to-text, `rosie stt-bench`.
- sherpa-onnx voices (`rosie voices`, `rosie say`, default `kokoro-emma`).
- "Hey Rosie" wake word (openWakeWord, plus a spoken-name fallback that needs no training).
- `rosie voice` loop with barge-in; Telegram voice notes in and out.
- [Walkthrough](docs/WALKTHROUGH-v0.4.md).

## v0.3 "daily-usable" (2026-11-26)

- Own SQLite scheduler (decision 0002); reminders with snooze and one follow-up.
- Telegram bot allowlisted to one chat; Windows toasts, routed by presence.
- Morning brief and nightly review.
- [Walkthrough](docs/WALKTHROUGH-v0.3.md).

## v0.2 "she remembers" (2026-11-26)

- rosie-vault layout and git sync; path-guarded vault writer.
- Facts store, tasks in Obsidian Tasks format, search across both vaults.
- Relevant memories and urgent tasks in every reply.
- [Walkthrough](docs/WALKTHROUGH-v0.2.md).

## v0.1 "talks in terminal" (2026-11-25)

- Config (D:\Rosie on Windows), logging with secret masking, local-first LLM client.
- Tool registry, agent loop with step cap, safety gate enforcing `permissions.yaml`.
- `SOUL.md` persona, `rosie chat`, clock and note-reader tools, `rosie doctor`.
- [Walkthrough](docs/WALKTHROUGH-v0.1.md).
