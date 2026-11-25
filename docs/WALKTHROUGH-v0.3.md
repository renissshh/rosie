# v0.3 walkthrough: "daily-usable"

Sprint 3 makes Rosie act on her own at the right moments: reminders, a morning brief,
a nightly review, and reaching you on the laptop or the phone.
Builds on [v0.2](WALKTHROUGH-v0.2.md).

## A day with Rosie

| Time | What happens |
| --- | --- |
| 07:30 | Morning brief written to `daily/2026-11-27.md`; one line on your screen or phone: "Top 3: DBMS normal forms; gym; call mom (1 overdue)" |
| 18:00 | Reminder "gym" as a Windows toast (you're at the laptop) |
| 18:15 | Not marked done: one follow-up, "Still pending: gym" |
| 18:30 | Still nothing: Rosie stops and writes "18:30 skipped: gym" in today's note |
| 22:00 | Nightly review on Telegram: three questions, one message each |
| 22:05 | Answers saved; tomorrow's top 3 become tasks and a draft plan |

## New commands

| Command | What it does |
| --- | --- |
| `rosie telegram` | Answers on Telegram (one allowlisted chat), runs reminders, brief and review |
| `rosie brief` | Prints today's brief |
| `rosie review` | Nightly review in the terminal |
| In chat: "remind me at 9pm to call mom", "every weekday 7am gym" | `set_reminder` and friends |

## How it fits together

```text
             Scheduler (SQLite, IST, missed runs merged)
             /            |                  \
     Reminders      MorningBrief 07:30    NightlyReview 22:00
  fire -> follow-up        |                    |
   -> "skipped" note       v                    v
             \        daily/<date>.md      answers + draft plan
              \
               Router: input in last 5 min? -> Windows toast
                                    else     -> Telegram   (each is the other's backup)
```

## Design decisions worth explaining

| Decision | Why |
| --- | --- |
| Own 150-line scheduler, not APScheduler | APScheduler persists jobs only via SQLAlchemy; Rosie needs four rules. See decisions/0002 |
| One follow-up, then log | Nagging gets ignored; a "skipped" line feeds the nightly review instead |
| Long polling, not webhooks | No open port on the laptop, works behind college Wi-Fi |
| Token never in errors | The Bot API puts the token in every URL, so errors report only the error type; the log masker also catches it (a bug found and fixed this sprint) |
| Toast text via env vars | Reminder text can't inject PowerShell |
| Brief and review are plain code | They work even when Ollama is down |

## Needs you (after exams)

Telegram: `docs/SETUP-TELEGRAM.md` (5 minutes, a BotFather token in `.env`).

## Numbers

- 287 tests on Ubuntu and Windows
