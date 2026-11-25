# 0001: What Rosie may do on her own

Date: 2026-11-25 · Decided by: renissshh · Status: accepted

## Decision

| Rosie does it herself | Rosie asks every time | Rosie never does it |
| --- | --- | --- |
| Manage tasks and reminders | Create or change calendar events | Write to or delete from your own vault |
| Log study, gym, daily reviews | Draft or send email | Payments |
| Read your Obsidian vault (read only) | Message anyone except you | |
| Search the web | Open apps / run allowlisted scripts | |
| Delete her own notes in rosie-vault | | |

Unprompted contact: morning brief, nightly review and due reminders only.
She stays silent during college and study blocks; reminders wait until the block ends.

The machine-readable version is `config/permissions.yaml`. Any action not listed is **ask**.

## Why

- Everything Rosie does freely stays inside her own vault or is read-only, so a mistake
  can't touch other people or your own notes.
- Deleting her own notes freely is safe because `rosie-vault` is a git repo: every
  deleted note can be restored from history.
- Anything that reaches other people or the laptop needs a yes, because those actions
  can't be undone by Rosie.

## Consequences

- The safety gate (Sprint 1) loads `config/permissions.yaml` and fails closed: an unknown
  action or an unreadable file means "ask".
- Tests must prove the deny list holds even if the LLM requests those actions directly.
