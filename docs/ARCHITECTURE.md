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

## Invariants (each one has a test)

1. Rosie never writes outside `rosie-vault`. (config overlap guard; `read_note` resolves paths and refuses anything outside the user vault; `VaultWriter` refuses every path outside rosie-vault, tested against 15 escape attempts)
2. Secrets never reach logs.
3. The cloud model is only called when the local model fails.
4. Denied actions never run, even if the model requests them directly; unknown actions and a broken policy file mean "ask".
