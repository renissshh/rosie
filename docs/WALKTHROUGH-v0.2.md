# v0.2 walkthrough: "she remembers"

Sprint 2 gives Rosie her own vault, a memory, a task list and search across both vaults.
Builds on [v0.1](WALKTHROUGH-v0.1.md).

## What's new

```text
You: remember that my DBMS exam is on 12 Dec
Rosie wants to remember a fact about the user for later: remember_fact(text='DBMS exam is on 12 Dec', topic='study')
Allow? [y/N] y
Rosie: Noted. DBMS exam, 12 Dec.

You: add "revise normal forms" for friday, high priority
Rosie: Added: revise normal forms (high), due Fri 27 Nov.

You: what do I have on DBMS?
Rosie: Your exam is on 12 Dec, "revise normal forms" is due Friday, and your
       Sem 3/DBMS note covers 1NF to 3NF.
```

| Command or tool | What it does |
| --- | --- |
| `rosie vault` | Creates `D:\Rosie\rosie-vault` (daily, tasks, memory, study-log, training-log) and syncs it with git |
| `remember_fact`, `update_fact`, `forget_fact`, `recall_facts` | Facts in `memory/<topic>.md`, one line each |
| `add_task`, `list_tasks`, `complete_task` | Tasks in `tasks/tasks.md`, Obsidian Tasks format |
| `search_notes` | Full-text search over your vault and hers, with snippets |
| (automatic) | Relevant facts and today's/overdue tasks go into every reply |

## How the pieces fit

```text
            rosie-vault (markdown, git)          your vault (read only)
                 ^          |                           |
   VaultWriter --+          +------> NoteIndex <--------+
 (only writer,     FactStore / TaskStore   (SQLite FTS5, D:\Rosie\index)
  path guard)            |                    |
                         +--> ContextBuilder -+--> system prompt, every reply
```

- **Markdown is the source of truth.** Facts and tasks are plain lines you can edit in
  Obsidian; Rosie reads your edits back. SQLite is only an index and can be deleted.
- **One writer.** `VaultWriter` is the only code that writes notes. It resolves every path and
  refuses `..`, absolute, drive-letter, UNC and symlink escapes, `.git` and non-markdown
  files. Tests try 15 escapes and check that no file anywhere changed.
- **Obsidian-native formats.** Facts end in block ids (`^a1b2c3`), tasks use the Tasks
  plugin's emoji (⏫ 📅 ✅), so links and queries work in Obsidian too.
- **Git as undo.** Rosie commits as "Rosie", so her changes are visible and reversible.
  Offline sync keeps the local commit and pushes next time.

## Permissions used

| Tool | Action in `config/permissions.yaml` | Result |
| --- | --- | --- |
| tasks | `tasks.manage` | runs freely |
| `forget_fact` | `vault.rosie.delete` | runs freely (git keeps history) |
| `search_notes` | `vault.user.read` | runs freely |
| `remember_fact`, `update_fact` | `memory.write` (not decided yet) | asks every time |

## Numbers

- 199 tests on Ubuntu and Windows
