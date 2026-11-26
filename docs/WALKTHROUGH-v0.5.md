# v0.5 walkthrough: "opens at login"

Sprint 5 gives Rosie a face on the desktop: a small floating orb with the Day Ring
around it, a Command Deck next to it, a tray icon, Ctrl+Space, and start-at-login.
Builds on [v0.4](WALKTHROUGH-v0.4.md). Full guide: [UI.md](UI.md).

## What works

```text
login
  -> orb appears bottom-right (grey while the core starts and checks its health)
  -> core answers: the orb breathes teal; the Day Ring shows today's plan
19:00  study block starts         -> orb dims (focus); only urgent reminders show
21:00  study block ends           -> held reminder pulses amber, its dot on the ring too
Ctrl+Space / click                -> "listening" (with `rosie serve --voice`) or the deck
right-click                       -> Command Deck: Top 3, Now/Next, streak, countdown,
                                     transcript, text box, + Study / + Gym / + Task
Ollama not running                -> dashed amber ring; the deck says what to run
```

Try it without building the app: `rosie serve` in one terminal, `cd ui; npm run dev` in
another, then open http://localhost:1420 (the orb) and http://localhost:1420/#deck.

## The pieces

```text
ui/src-tauri (Rust)   window placement, tray, Ctrl+Space, autostart, starts `rosie serve`
ui/src (React)        orb, Day Ring, Command Deck; pure modules for every rule:
                        orbState.ts (which look wins), ringGeometry.ts (clock maths),
                        deckModel.ts (now/next), bridge.ts (reconnecting WebSocket)
src/rosie/bridge.py   the WebSocket on 127.0.0.1:8765 (JSON messages, see UI.md)
src/rosie/day.py      today's blocks + reminders, focus on/off
src/rosie/quicklog.py study/training logs, streak, brief cards
src/rosie/health.py   `rosie doctor` checks as an event
```

## Design decisions worth explaining

| Decision | Why |
| --- | --- |
| One WebSocket, JSON messages with a `type` | Easy to read in devtools, easy to test from Python with a plain client; the same core serves the orb, Telegram and voice |
| Localhost only, plus an Origin check | Any web page can open `ws://127.0.0.1`; refusing foreign origins stops a website from driving Rosie |
| One writer queue per window, answers queued from the worker thread | A race showed up in tests: a reply could overtake the "thinking" state sent just before it. Queuing both from the same thread fixed the order for good |
| The core decides focus and health; the orb only draws | Rules live in one place (Python) and the UI stays a thin, testable reducer |
| Pure TypeScript modules for every rule | 51 UI tests run in under a second with no browser and no Tauri |
| `orbState.ts` next to `Orb.tsx`, never `orb.ts` | Windows CI caught it: on Windows `./orb` and `./Orb` are the same file. A test now blocks such names |
| Autostart once, on the first release run | "Opens at login" by default, but the tray tick is yours; dev builds never register |
| Python core started by the orb, not bundled | No PyInstaller step to maintain; `ROSIE_CORE` points at a venv if `rosie` isn't on PATH |

## Needs you (after exams, optional)

- Install Rust and Node (docs/UI.md), then `cd ui; npm install; npm run tauri dev`
- Add your real `day_blocks` and `countdowns` to `config/rosie.yaml` (examples in
  `config/rosie.example.yaml`)
- If `rosie` isn't on PATH at login, set the `ROSIE_CORE` user environment variable
