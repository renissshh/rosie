# v0.1 walkthrough: "talks in terminal"

What Rosie can do at the end of Sprint 1, and how one message travels through the code.
Useful as an interview explanation: every box below is one small module with its own tests.

## What works

```text
> rosie doctor
[ok]   Python: 3.12
[ok]   Data folder: D:\Rosie
[ok]   LLM: qwen3:8b at http://localhost:11434/v1
[ok]   Your vault: D:\Obsidian\MyVault (read only)
[ok]   Permissions: 16 actions decided
All good. Run `rosie chat`.

> rosie chat
Rosie: Evening, VinsmokE. Type /help for commands.
You: what's in my DBMS note?
Rosie: Your DBMS note covers normal forms: 1NF, 2NF and 3NF. Want a quick quiz?
```

- Chat in the terminal with memory of the current conversation (`/reset` clears it)
- Tells the date and time in IST
- Reads any note from your Obsidian vault by name, never changes it
- Asks `Allow? [y/N]` before anything on the "ask" list; refuses anything on the "deny" list
- Logs every tool call to `D:\Rosie\logs\tool_calls.jsonl`

## One message, step by step

```text
You type          chat.py           prompt.py            agent.py                 llm.py
"DBMS note?" -->  ChatSession  -->  SOUL.md + time  -->  loop (max 8 steps)  -->  Ollama (local)
                  (history)         + tool names          |                       cloud only if
                                                          v                       Ollama is down
                                                     safety.py: allow/ask/deny
                                                          |
                                                          v
                                                     tools.py -> builtin_tools.read_note
```

1. **`chat.py`** adds your message to the history and builds a fresh system prompt.
2. **`prompt.py`** joins `SOUL.md` (her personality), the current IST time and the tool list.
3. **`agent.py`** sends everything to the model with each tool's JSON schema.
4. The model replies with a *tool call*: `read_note(name="DBMS")`.
5. **`tools.py`** checks the arguments against the schema (wrong types never reach code).
6. **`safety.py`** looks up the tool's action (`vault.user.read`) in
   `config/permissions.yaml`: `allow`, so it runs without asking.
7. **`builtin_tools.py`** resolves the path, proves it is inside your vault, reads it.
8. The note text goes back to the model, which writes the answer you see.
9. If the model keeps calling tools, the loop stops after `max_agent_steps` and forces an answer.

## Design decisions worth explaining

| Decision | Why |
| --- | --- |
| One OpenAI-compatible client | Ollama and free cloud APIs speak the same format, so swapping models is config, not code |
| Local first, cloud fallback | Free and private; the cloud is only used when Ollama is down |
| Permissions in YAML, fail closed | The owner decides, not the model. Unknown action or broken file means "ask" |
| Tier floor | External/system tools always ask, even if someone edits the YAML to "allow" |
| Errors go back to the model as text | A failing tool can't crash a conversation; Rosie explains instead |
| History trimmed by whole turns | A tool call is never separated from its result, which models reject |
| Injectable input/output/clock | Every piece is tested without a real model, terminal or clock |

## Numbers

- 126 tests, run on Ubuntu and Windows in CI on every push
- No secrets in the repo: keys are referenced by env var name only

## Next: Sprint 2 "she remembers"

Rosie gets her own vault (`D:\Rosie\rosie-vault`) for facts and tasks, with a path guard
that proves she can't write anywhere else.
