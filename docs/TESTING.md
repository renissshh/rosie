# Testing Rosie

Four layers, all run by CI (`.github/workflows/ci.yml`) on every push to `dev` and `main`.

| Layer | What it covers | Run it | CI job |
|---|---|---|---|
| Python unit tests | the core: agent, safety gate, vault, tasks, reminders, coaches, bridge... | `python -m pytest -q` | `test` (Ubuntu + Windows) |
| UI tests | the React orb and Command Deck with a fake socket | `cd ui && npm test` | `ui` |
| Rust tests | the Tauri shell (core start/stop, tray, autostart) | `cd ui/src-tauri && cargo test` | `ui-shell` (Windows) |
| End-to-end | real `rosie` commands; real `rosie serve` + orb page + browser | see below | `test` (terminal), `e2e` (browser) |

Two integration tests sit in the Python layer: `tests/test_whole_day.py` runs a whole day
of the real schedule (brief, reminders and their follow-ups, nightly review, backups) on a
fake clock in about a second, including a laptop that slept all day and a core restarted
three times; `tests/test_release.py` guards versions, the changelog and doc links.

Before every commit: `ruff format . && ruff check . && python -m pytest -q`.

## End-to-end tests (`tests/e2e`)

Both kinds share one fake model (`tests/e2e/rosie_fakes.py`): a tiny OpenAI-compatible
server that answers the way Ollama would, with scripted tool calls, so the tests are
fast, free and the same every time.

### In the terminal (`test_cli_e2e.py`)

The real `rosie` commands as separate processes on a fresh data folder, in the order a
new user runs them: `rosie vault` creates the vault folders, `rosie doctor` says "All
good", `rosie chat` (typed through stdin) uses tools and the safety gate reads your
`n` / `y`, `rosie brief` lists the task chat added, and with the model down chat explains
what to run and keeps going. No browser needed, so they run in the normal `test` job.

### In the browser (`test_orb_e2e.py`)

These start the real core with `rosie serve`, open the built orb page and Command Deck in
headless Chromium, and click through them like you would.

What they prove:

- a typed message reaches the agent and the reply shows in the transcript;
- "add a task: ..." makes Rosie call `add_task`, the task is written to
  `rosie-vault/tasks/tasks.md`, shows in Top 3, and ticking it marks it `[x]` on disk;
- the safety gate asks in the deck ("Rosie asks" card): **Deny** means nothing is
  written to `memory/`, **Allow** saves the fact;
- the orb opened before the core (the login race) shows grey, then turns idle by itself
  once `rosie serve` starts;
- with the model down (Ollama not running) the orb shows "unwell", the deck's "Needs a
  hand" card says to run `ollama serve`, and a message gets the "can't reach my brain"
  answer instead of an error.

Run them on your laptop:

```powershell
cd ui; npm ci; npm run build; cd ..
pip install -e ".[dev,e2e]"
python -m playwright install chromium
python -m pytest tests/e2e -v   # the terminal tests also run without these steps
```

They use ports 8765 (the core) and 1420 (the page), so stop the orb first; if either
port is busy, or the page isn't built, or Playwright isn't installed, they are skipped.
In CI `ROSIE_E2E=1` turns those skips into failures, so they can't quietly stop running.
