# Reliability: backups, limits, recovery

What keeps Rosie (and your data) safe when things go wrong.

## Vault backups

Every day at 03:00 Rosie zips rosie-vault (without its `.git` folder) to
`D:\Rosie\backups\rosie-vault-YYYY-MM-DD.zip` and keeps the newest 14. If the laptop was
asleep at 03:00, the backup runs once when it wakes. The zip is written under a
temporary name and renamed when complete, so a crash never leaves half a backup.

On top of that, rosie-vault is a git repository: every change can be undone from
history, and with a remote it's also on GitHub.

Restore: close Rosie, rename the broken `rosie-vault` folder, unzip the backup into a
new `rosie-vault` folder, then run `rosie vault` to reconnect it to git.

## Rate limits

A runaway loop or a stuck client shouldn't be able to burn through a free quota or
flood the agent:

| What | Limit | What happens past it |
| --- | --- | --- |
| Telegram messages to Rosie | 20 a minute | She answers "Slow down a little: try again in N s" without calling the LLM |
| Messages from the orb / Command Deck | 20 a minute | The deck shows "too many messages; try again in N s" |
| Cloud fallback LLM | `max_per_minute` under `fallback_llm` in `rosie.yaml` (e.g. 10) | The call isn't sent; if Ollama is also down she says she can't think right now |

The local model (Ollama) has no limit: it's free and on your machine. The agent's own
loop is already capped at `max_agent_steps` tool rounds per message.
