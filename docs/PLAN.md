# Rosie build plan (source of truth for nightly sessions)

Model: agile, six 1-week sprints, one build session per night (11:31 PM to 3:30 AM IST).
Started: **Nov 25, 2026**. Target: **v1.0 tagged Jan 5, 2027**.
Full design doc: https://claude.ai/artifact/3t85cRBHCQbzeY97eMX55X

Rules for every night:
- Work on `dev`. At least 5 commits, each a real unit (code + test + docs). Never pad.
- `ruff check`, `ruff format --check`, `pytest` must pass before every commit.
- End with `docs/devlog/YYYY-MM-DD.md`: done / blocked / needs-you.
- Night 7 of each sprint: merge `dev` into `main`, tag `v0.N`.
- If an item is already done, take the next one. If a night runs out, note where it stopped.
- Items marked **[needs you]** wait in the devlog until the user does them. Never block a night on them; move to the next item.
- The user has MCA exams until Dec 23: keep needs-you items to a minimum before then.

Status legend: `[x]` done, `[ ]` to do.

## Sprint 1: Foundation (Nov 25 to Dec 1) -> v0.1 "talks in terminal"
- [x] Scaffold, pyproject, ruff, pytest, CI (Ubuntu + Windows)
- [x] Config loader (YAML + env, D:\Rosie on Windows, vault-overlap guard)
- [x] Logging with secret masking
- [x] LLM client: OpenAI-compatible, local Ollama first, free-tier fallback
- [x] Tool registry (JSON-schema tools, typed handlers)
- [x] Agent loop with step cap and tool-call log
- [x] Safety gate: enforce `config/permissions.yaml` (allow / ask / deny, fail closed) + tests. Decisions: docs/decisions/0001
- [x] `config/SOUL.md` persona + system prompt builder
- [x] Terminal chat (`rosie chat`) with conversation history
- [x] First tools: current time/date, read a note from the user vault
- [x] Windows setup guide (`docs/SETUP-WINDOWS.md`) + `rosie doctor` **[needs you: run it after exams]**
- [x] Merge, tag v0.1, walkthrough doc (`docs/WALKTHROUGH-v0.1.md`)

## Sprint 2: Memory + vault (Dec 2 to Dec 8) -> v0.2 "she remembers"
- [x] rosie-vault layout: daily/ tasks/ memory/ study-log/ training-log/ + git sync
- [x] Vault writer with path guard; tests prove no writes outside rosie-vault
- [x] Facts store: remember / update / forget (markdown + SQLite index)
- [x] Tasks: add / list / complete, due dates, priorities
- [x] Read-only index of the user's vault; search across both vaults
- [x] Context builder: relevant memories in every reply
- [x] Merge, tag v0.2, walkthrough doc (`docs/WALKTHROUGH-v0.2.md`)

## Sprint 3: Reminders + Telegram (Dec 9 to Dec 15) -> v0.3 "daily-usable"
- [x] Scheduler, persisted jobs (own SQLite scheduler instead of APScheduler: docs/decisions/0002)
- [x] Reminders: one-off, recurring, snooze, one follow-up then log skipped
- [x] Telegram bot allowlisted to one chat id (`docs/SETUP-TELEGRAM.md`) **[needs you: BotFather token in .env]**
- [x] Windows desktop notifications; route desktop vs Telegram by presence
- [x] Morning brief (Top 3, schedule, overdue, one avoided task)
- [x] Nightly review (3 questions -> daily/, drafts tomorrow)
- [x] Merge, tag v0.3, walkthrough doc (`docs/WALKTHROUGH-v0.3.md`)

## Sprint 4: Voice (Dec 16 to Dec 22) -> v0.4 "hands-free"
- [x] Mic capture + voice activity detection
- [ ] Speech-to-text (faster-whisper) + latency benchmark
- [ ] Text-to-speech (sherpa-onnx), choose Rosie's voice
- [ ] "Hey Rosie" wake word (livekit-wakeword / openWakeWord) **[needs you: voice samples, after exams]**
- [ ] Wake -> listen -> think -> speak loop, barge-in
- [ ] Telegram voice notes in/out
- [ ] Merge, tag v0.4

## Sprint 5: Orb UI + autostart (Dec 23 to Dec 29) -> v0.5 "opens at login"
- [ ] Tauri 2 + React shell, transparent always-on-top window
- [ ] WebSocket bridge to the Python core (sidecar)
- [ ] Orb states: idle, listening, thinking, speaking, nudge, focus
- [ ] Day Ring: today's blocks drawn live from the schedule
- [ ] Command Deck: brief cards, text box, transcript, quick log
- [ ] Autostart at login, health check, tray, Ctrl+Space
- [ ] Merge, tag v0.5

## Sprint 6: Coaches + ship (Dec 30 to Jan 5) -> v1.0
- [ ] Study coach: sessions, weak-subject detection, quizzes from notes
- [ ] Training coach: voice set logging, progression, stall alerts
- [ ] Always-on server option (Docker) sharing rosie-vault via git
- [ ] Identity: emblem SVG, icons, wordmark
- [ ] Hardening: error recovery, vault backups, rate limits
- [ ] Windows installer script, user guide, demo GIF
- [ ] Final tests, merge, tag v1.0
