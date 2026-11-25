# Architecture (v0.0, updated each sprint)

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

## Invariants (each one has a test)

1. Rosie never writes outside `rosie-vault`. (config overlap guard today; vault writer path guard in Sprint 2)
2. Secrets never reach logs.
3. The cloud model is only called when the local model fails.
