# Architecture (v0.1, updated each sprint)

Step-by-step tour of one message: [WALKTHROUGH-v0.1.md](WALKTHROUGH-v0.1.md).

```
 Laptop: orb + voice        LLM API (Ollama local / free-tier cloud)        Phone: Telegram
          \                              |                                     /
           +-------------------->  Agent loop + safety gate  <-----------------+
                                         |
              +------------+-------------+--------------+
              |            |             |              |
            Tools      Scheduler       Memory       Vault guard
                                         |              |
                                 user vault (RO)    rosie-vault (RW, git-synced)
```

## Modules today

| Module | Responsibility |
| --- | --- |
| `rosie.config` | Defaults < `rosie.yaml` < `ROSIE_*` env. `D:\Rosie` on Windows. Refuses overlapping vaults. |
| `rosie.logging_setup` | Console + rotating file log; masks tokens and API keys. |
| `rosie.llm` | One OpenAI-compatible client for Ollama and cloud; `FallbackLLM` is local-first. |
| `rosie.tools` | Tool registry: JSON-schema arguments, risk tier per tool. |
| `rosie.agent` | Agent loop: LLM -> tools -> LLM, step cap (`max_agent_steps`), gate before every call, JSON-lines tool-call log. |
| `rosie.safety` | Safety gate: enforces `config/permissions.yaml` (allow / ask / deny), tier floor for external/system tools, fails closed. |
| `rosie.prompt` | System prompt = `SOUL.md` persona + current IST time + available tools. `D:\Rosie\SOUL.md` overrides `config/SOUL.md`. |
| `rosie.chat` | `rosie chat`: history kept per session (trimmed by whole turns), yes/no prompt for the gate, friendly message when Ollama is down. |
| `rosie.builtin_tools` | `get_datetime` (IST clock) and `read_note` (user vault, read only, path-guarded, finds notes by name). |
| `rosie.doctor` | `rosie doctor`: checks Python, `D:\Rosie`, Ollama + model, fallback key (name only), vault, permissions. |
| `rosie.vault` | rosie-vault layout (daily/ tasks/ memory/ study-log/ training-log/) and git sync: commit as "Rosie", pull --rebase, push; offline keeps the local commit. |
| `rosie.vault_writer` | The only writer: notes in rosie-vault only (no `..`, absolute, drive, UNC, symlink escapes, `.git`, non-`.md`), atomic writes. |
| `rosie.memory` | Facts: one markdown file per topic in `memory/`, Obsidian block ids (`^a1b2c3`), rebuildable SQLite FTS5 index; remember / update / forget / recall tools. |
| `rosie.tasks` | Tasks in `tasks/tasks.md`, Obsidian Tasks format (⏫🔼🔽 priority, 📅 due, ✅ done); due dates like "friday" or "in 3 days"; add / list / complete tools. |
| `rosie.search` | FTS5 index of both vaults in `D:\Rosie\index\notes.db`, refreshed incrementally by size/mtime; `search_notes` tool with snippets. |
| `rosie.context` | Before each reply: facts matching the message (max 5) + tasks due today/overdue go into the system prompt; failures only drop the context. |

## Invariants (each one has a test)

1. Rosie never writes outside `rosie-vault`. (config overlap guard; `read_note` resolves paths and refuses anything outside the user vault; `VaultWriter` refuses every path outside rosie-vault, tested against 15 escape attempts)
2. Secrets never reach logs.
3. The cloud model is only called when the local model fails.
4. Denied actions never run, even if the model requests them directly; unknown actions and a broken policy file mean "ask".
