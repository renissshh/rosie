# Rosie's orb (desktop UI)

The orb is a small Tauri 2 + React window in `ui/`: transparent, always on top, no title
bar, no taskbar button. It sits in the bottom-right corner of the screen, above the
taskbar, and you can drag it anywhere.

```
ui/
  src/            React + TypeScript (what you see)
  src-tauri/      Rust shell (the native window), tauri.conf.json, icons
```

## Run it (Windows)

Needs once: [Rust](https://rustup.rs) (default MSVC toolchain), Node.js 22 LTS, and the
"Desktop development with C++" workload from Visual Studio Build Tools. WebView2 is
already part of Windows 10/11.

```powershell
cd ui
npm install
npm run tauri dev       # live-reloading orb
npm run tauri build     # installer in ui\src-tauri\target\release\bundle\nsis
```

## Tests

```powershell
cd ui
npm test                       # React components (Vitest + jsdom)
npm run typecheck
cd src-tauri; cargo test       # window placement maths
```

CI runs the React tests on Ubuntu and the Rust tests on the Windows runner.

## Why these window settings

| Setting | Why |
| --- | --- |
| `transparent`, `decorations: false`, `shadow: false` | Only the round orb paints; no square frame |
| `alwaysOnTop` | The Day Ring stays visible over other apps |
| `skipTaskbar` | Rosie lives in the tray (Sprint 5), not the taskbar |
| CSP `connect-src ws://127.0.0.1:8765` | The page may talk only to Rosie's own core on this laptop |

## What the orb shows

| Look | What you see | When |
| --- | --- | --- |
| Offline | Grey, no glow | The core isn't running or reachable (the orb keeps retrying) |
| Idle | Slow breathing teal glow | Default |
| Listening | Inner ring opens and pulses | "Hey Rosie", or a click on the orb |
| Thinking | Three particles orbit the core | The agent is working on an answer |
| Speaking | Core pulses quickly | Her voice is playing |
| Nudge | Amber pulse | A reminder fired; click to dismiss, fades after a minute |
| Focus | Dimmed | A study block is on: only urgent reminders show, the rest wait until it ends |

When two apply, the one higher in the table (below Offline) wins: a reminder that fires
while she is speaking pulses once she's done. The rules are in `ui/src/orbState.ts` and are
unit-tested. With "reduce animations" on in Windows, the looks are colour-only.

Voice in the orb: start the core with `rosie serve --voice` (needs the `[voice]` extras,
see docs/VOICE.md). Clicking the orb then works like saying "Hey Rosie", and also stops
her mid-sentence. Without `--voice`, the orb works by typing (Command Deck).

## The Day Ring

Around the orb is a 24-hour clock of your day: midnight at the top, 06:00 on the right,
noon at the bottom, 18:00 on the left. A small white hand shows the time.

- **Blocks** come from `day_blocks` in `config/rosie.yaml` (see `config/rosie.example.yaml`):
  college blue, study teal, gym pink, review purple, sleep slate. Each block is faint
  until its time passes, then it fills in, so you can see at a glance how much of the
  plan is behind you. Blocks may cross midnight (sleep 23:30 -> 06:30) and can be
  limited to some weekdays (`days: [mon, tue]`).
- **Dots** are today's reminders, the morning brief and the nightly review. When a
  reminder fires, its dot pulses amber with the orb.
- **Focus**: while a `study` block is on, the core tells the orb (`focus`), the orb
  dims and holds back reminders that aren't urgent until the block ends.

The core recomputes the ring every 30 seconds (`src/rosie/day.py`) and only sends it
when something changed: a new reminder, or a new day after midnight.

## The Command Deck

Right-click the orb (or press Ctrl+Space) to open the Command Deck, a small window
next to it. Closing it only hides it.

- **Rosie asks**: when the safety gate needs your yes (deleting a note, say), the
  question appears at the top with Allow / Deny. No answer in 60 seconds means no.
- **Top 3 today**: your most urgent open tasks; tick one to mark it done.
- **Now / Next**: the block you're in and the next block or reminder; your **study
  streak** (days in a row with a study entry); the nearest **countdown** from
  `countdowns` in `rosie.yaml`; and how many tasks are overdue.
- **Conversation**: the live transcript, typed or spoken.
- **Text box**: Enter asks Rosie. Or type and tap a quick-log button:

| Button | Writes to rosie-vault | Example |
| --- | --- | --- |
| + Study | `study-log/YYYY-MM-DD.md`, `- 19:40 DBMS normal forms (45 min)` | `DBMS normal forms 45m` (`1h 30m`, `90 mins` work too) |
| + Gym | `training-log/YYYY-MM-DD.md`, `- 18:10 bench 3x8 40kg` | `push day, bench 3x8 40kg` |
| + Task | a new task in `tasks/tasks.md` | `buy notebook` |

Without `--voice`, clicking the orb opens the deck too, since typing is the way to talk.

## How the orb talks to Rosie's core

The orb is only a face; everything Rosie knows lives in the Python core. They talk over
one WebSocket on `ws://127.0.0.1:8765` (`src/rosie/bridge.py` and `ui/src/bridge.ts`):

```
 orb window ──ask / ping / confirm_reply──>  rosie serve  ──> agent, tasks, reminders
            <──state / reply / nudge ...───               <── scheduler, voice loop
```

When the orb opens it checks whether a core is already listening. If not, it starts
`rosie serve` itself (or the program in the `ROSIE_CORE` environment variable, e.g.
`D:\Rosie\.venv\Scripts\rosie.exe`) with no console window, and stops it when the orb
quits. The orb keeps reconnecting (1 s, 2 s, 4 s ... 10 s), so starting order never matters.

| Message | Direction | Meaning |
| --- | --- | --- |
| `hello {version}` | core -> orb | First message on every connection |
| `ping` / `pong` | orb -> core -> orb | Is the core alive? |
| `ask {text}` | orb -> core | A typed message; answered with `reply {text}` |
| `listen` | orb -> core | Start listening now (click on the orb, Ctrl+Space) |
| `state {state}` | core -> orb | `idle`, `listening`, `thinking` or `speaking` |
| `focus {on, label}` | core -> orb | A study block started (`on: true`) or ended |
| `day {date, blocks, marks}` | core -> orb | Today's Day Ring: blocks `{start, end, kind, label}`, marks `{at, kind, text}` |
| `transcript {role, text}` | core -> orb | One line of the conversation (`you` or `rosie`) |
| `nudge {title, text, urgent}` | core -> orb | A reminder fired (`urgent` ones get through focus) |
| `confirm {id, question}` | core -> orb | The safety gate wants your yes/no |
| `confirm_reply {id, allow}` | orb -> core | Your answer (only `true` means yes; 60 s silence = no) |
| `brief {top3, overdue, streak, countdown}` | core -> orb | The deck's cards (sent when they change) |
| `log {what, text}` | orb -> core | Quick log: `what` is `study`, `gym` or `task`; answered with `logged {text}` |
| `done {id}` | orb -> core | Tick a task; answered with `logged {text}` |
| `error {text}` | core -> orb | A request could not be handled |

A request may carry an `id`; the answer repeats it. Safety: the core listens on
127.0.0.1 only, refuses browser connections from any page other than Rosie's own window
(a web page could otherwise open `ws://127.0.0.1:8765`), and caps messages at 64 KB.
