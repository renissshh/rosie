# Testing Rosie

Four layers, all run by CI (`.github/workflows/ci.yml`) on every push to `dev` and `main`.

| Layer | What it covers | Run it | CI job |
|---|---|---|---|
| Python unit tests | the core: agent, safety gate, vault, tasks, reminders, coaches, bridge... | `python -m pytest -q` | `test` (Ubuntu + Windows) |
| UI tests | the React orb and Command Deck with a fake socket | `cd ui && npm test` | `ui` |
| Rust tests | the Tauri shell (core start/stop, tray, autostart) | `cd ui/src-tauri && cargo test` | `ui-shell` (Windows) |
| End-to-end | real `rosie serve` + real orb page + real browser | see below | `e2e` (Ubuntu + Windows) |

Two integration tests sit in the Python layer: `tests/test_whole_day.py` runs a whole day
of the real schedule (brief, reminders and their follow-ups, nightly review, backups) on a
fake clock in about a second, including a laptop that slept all day and a core restarted
three times; `tests/test_release.py` guards versions, the changelog and doc links.

Before every commit: `ruff format . && ruff check . && python -m pytest -q`.

## End-to-end tests (`tests/e2e`)

These start the real core with `rosie serve`, open the built Command Deck in headless
Chromium, and click through it like you would. Only the language model is fake: a tiny
OpenAI-compatible server in the test answers the way Ollama would, with scripted tool
calls, so the tests are fast, free and the same every time.

What they prove:

- a typed message reaches the agent and the reply shows in the transcript;
- "add a task: ..." makes Rosie call `add_task`, the task is written to
  `rosie-vault/tasks/tasks.md`, shows in Top 3, and ticking it marks it `[x]` on disk;
- the safety gate asks in the deck ("Rosie asks" card): **Deny** means nothing is
  written to `memory/`, **Allow** saves the fact.

Run them on your laptop:

```powershell
cd ui; npm ci; npm run build; cd ..
pip install -e ".[dev,e2e]"
python -m playwright install chromium
python -m pytest tests/e2e -v
```

They use ports 8765 (the core) and 1420 (the page), so stop the orb first; if either
port is busy, or the page isn't built, or Playwright isn't installed, they are skipped.
In CI `ROSIE_E2E=1` turns those skips into failures, so they can't quietly stop running.
