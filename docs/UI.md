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
