# Rosie

**R.O.S.I.E.: Reminders, Organization, Study, Insight, Execution.**

Rosie is a personal AI chief of staff that lives on a Windows laptop as a floating orb,
answers on Telegram from the phone, and keeps her own second brain in a separate
Obsidian vault. Say "Hey Rosie" and she tells you what matters today.

> Status: **in active development** (Sprint 1 of 6). See [docs/PLAN.md](docs/PLAN.md).

## What she will do (v1.0)

- Wake on "Hey Rosie" or Ctrl+Space and brief you: top 3 tasks, schedule, what's overdue
- Remind you on the desktop or on Telegram, depending on where you are
- Remember what you tell her, in her own vault (`rosie-vault`), never touching your notes
- Coach study and training: log sessions, spot skipped subjects, track progression
- Start automatically at login, with a "Day Ring" orb that shows your day at a glance

## Design choices

| Choice | Why |
| --- | --- |
| Local LLM via Ollama, free-tier cloud fallback | Free to run, private by default |
| Separate `rosie-vault` + read-only access to your vault | Your notes are never modified |
| All data on `D:\Rosie` (Windows) | Keeps the system drive clean |
| Python core + Tauri UI | One language for AI/voice/bot; tiny native desktop app |

## Try it

```bash
ollama pull qwen3:8b      # once
rosie chat                # /help, /tools, /reset, /exit
```

Today she can tell the date and time and read notes from your Obsidian vault
(set `user_vault_dir` in `config/rosie.yaml`): "what's in my DBMS note?".

When Rosie wants to do something that needs your yes (see `config/permissions.yaml`),
she asks `Allow? [y/N]` in the terminal; anything but `y` means no.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check . && ruff format --check .
python -m pytest
```

Configuration: copy `config/rosie.example.yaml` to `config/rosie.yaml` and `.env.example`
to `.env`. Secrets live only in `.env`.

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Credits: [CREDITS.md](CREDITS.md).

## License

MIT
