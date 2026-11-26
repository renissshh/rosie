# 0003: An always-on server shares rosie-vault through git, and owns the clock

Date: 2026-11-27 · Decided by: nightly build (can be revisited by renissshh) · Status: accepted

## Context

The laptop sleeps. An always-on box (an old PC, a free cloud VM) can keep Telegram
answering and send the morning brief at 07:30 even when the laptop is closed. Two Rosies
then need the same memory, tasks and logs, and must not both send the same brief.

## Decision

- **One vault, synced with git.** rosie-vault already is a git repo. Both machines run
  `git pull --rebase` + `git push` every 10 minutes (`vault_sync_minutes`) and once on
  exit. Notes are small Markdown files with one line per fact/task/log entry, so
  conflicting edits are rare and git's rebase handles most of them; a conflict is
  logged and retried next round, never lost.
- **One clock owner.** `clock: server` in the laptop's `rosie.yaml` tells the laptop
  that the server sends the brief and the nightly review; the laptop drops those jobs
  (even ones left from earlier runs). Telegram runs only on the server
  (`rosie server` = Telegram + reminders + brief/review + vault sync).
- **Reminders stay where they were made.** The scheduler database is per machine, not in
  the vault. A reminder set on the laptop fires on the laptop; one set on Telegram fires
  from the server.

## Why

- No new service or database: git and SSH/HTTPS are all that's needed, and every change
  stays undoable in history (decision 0001).
- "Who sends the brief" is one config line, easy to explain and test.
- Sharing the scheduler would mean a networked database and locking; not worth it for a
  one-person assistant.

## Consequences

- With `clock: server`, the laptop's Day Ring shows only reminders made on the laptop
  (the brief and review dots move to the server). Revisit if that's confusing in use.
- The server needs write access to the rosie-vault remote (a deploy key or a
  fine-grained token kept in the container's volume, never in the repo).
