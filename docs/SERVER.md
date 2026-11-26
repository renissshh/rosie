# Always-on server (optional)

Run Rosie on a machine that never sleeps (an old PC, a Raspberry Pi 5, a free cloud
VM) so Telegram answers and the morning brief arrives while the laptop is closed. The
server and the laptop share rosie-vault through git; see
[decision 0003](decisions/0003-always-on-server.md) for why it works this way.

```
laptop (orb, voice)  ── git pull/push every 10 min ──  GitHub: rosie-vault (private)
                                                           │
server (Docker): Telegram, reminders, brief, review ── git pull/push every 10 min
```

## Set up (about 15 minutes, once)

1. On the server, install Docker, clone this repo and create `.env` next to
   `docker-compose.yml` (same variables as `.env.example`: `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, optional `GEMINI_API_KEY`).
2. Start it:

   ```bash
   docker compose up -d
   docker compose exec ollama ollama pull qwen3:8b     # once; or use only the cloud fallback
   ```

3. Give the server its copy of rosie-vault (a fine-grained GitHub token with
   Contents: read and write on rosie-vault only, kept inside the container's volume):

   ```bash
   docker compose exec rosie git clone https://<TOKEN>@github.com/renissshh/rosie-vault /data/rosie-vault
   docker compose restart rosie
   ```

4. On the laptop, in `config/rosie.yaml`:

   ```yaml
   clock: server        # the server sends the brief and review now
   ```

   and stop running `rosie telegram` on the laptop (one bot at a time).

## What runs where

| | Laptop (`rosie serve`, `rosie chat`, `rosie voice`) | Server (`rosie server`) |
| --- | --- | --- |
| Orb, voice, Command Deck | yes | no |
| Telegram | no (when a server runs) | yes |
| Morning brief, nightly review | only with `clock: here` | yes |
| Reminders | the ones set on the laptop | the ones set on Telegram |
| rosie-vault | synced every 10 min | synced every 10 min |

`docker compose logs -f rosie` shows what she's doing. The image runs as a normal user,
keeps everything in the `rosie-data` volume, and checks itself every 5 minutes.
