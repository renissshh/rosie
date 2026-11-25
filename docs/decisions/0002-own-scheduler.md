# 0002: A small scheduler of our own instead of APScheduler

Date: 2026-11-26 · Decided by: nightly build (can be revisited by renissshh) · Status: accepted

## Context

The plan said "Scheduler (APScheduler, persisted jobs)". APScheduler 3 only persists jobs
through SQLAlchemy (plus a database driver), and APScheduler 4 is still pre-release. Rosie
needs very little: one-off times, daily and weekly times, and "every N minutes", stored so
they survive a reboot, with missed jobs run once when the laptop wakes up.

## Decision

`rosie.scheduler`: about 150 lines, jobs in SQLite (`D:\Rosie\index\scheduler.db`), standard
library only. Recurrence is computed in the user's time zone (IST). A job that was due while
the laptop was off runs **once** on the next tick (missed runs are merged, not replayed).

## Why

- No new heavy dependency; nothing extra to install on Windows.
- Every rule is plain code with tests that use a fake clock, easy to explain in an interview.
- Switching to APScheduler later only replaces this module; callers use `add` / `run_pending`.

## Consequences

- No cron syntax. If Rosie ever needs it, revisit this decision.
