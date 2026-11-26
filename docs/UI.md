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
| `state {state}` | core -> orb | `idle`, `listening`, `thinking` or `speaking` |
| `transcript {role, text}` | core -> orb | One line of the conversation (`you` or `rosie`) |
| `nudge {title, text}` | core -> orb | A reminder fired |
| `confirm {id, question}` | core -> orb | The safety gate wants your yes/no |
| `confirm_reply {id, allow}` | orb -> core | Your answer (only `true` means yes; 60 s silence = no) |
| `error {text}` | core -> orb | A request could not be handled |

A request may carry an `id`; the answer repeats it. Safety: the core listens on
127.0.0.1 only, refuses browser connections from any page other than Rosie's own window
(a web page could otherwise open `ws://127.0.0.1:8765`), and caps messages at 64 KB.
