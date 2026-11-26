"""Make the pictures in docs/images from the real orb page (not a mock-up).

    cd ui && npm run build && cd ..
    pip install playwright pillow && python -m playwright install chromium
    python scripts/make_demo.py

It serves ui/dist, replaces the page's WebSocket with a scripted fake core (the same
messages `rosie serve` sends), and screenshots each orb look and the Command Deck:

    docs/images/demo.gif        the orb going through its looks, about 10 seconds
    docs/images/orb-looks.png   all looks side by side
    docs/images/deck.png        the Command Deck

Only for documentation: nothing in Rosie imports it.
"""

from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "ui" / "dist"
OUT = ROOT / "docs" / "images"

DAY = {
    "type": "day",
    "date": "2026-11-26",
    "blocks": [
        {"start": "09:00", "end": "15:30", "kind": "college", "label": "College"},
        {"start": "17:00", "end": "18:00", "kind": "gym", "label": "Gym"},
        {"start": "19:00", "end": "21:00", "kind": "study", "label": "DBMS"},
        {"start": "22:00", "end": "22:15", "kind": "review", "label": "Review"},
        {"start": "23:30", "end": "06:30", "kind": "sleep", "label": "Sleep"},
    ],
    "marks": [
        {"at": "07:30", "kind": "brief", "text": "Morning brief"},
        {"at": "21:30", "kind": "reminder", "text": "call mom"},
        {"at": "22:00", "kind": "review", "text": "Nightly review"},
    ],
}
BRIEF = {
    "type": "brief",
    "top3": [
        {
            "id": "a1",
            "title": "Submit DBMS assignment",
            "due": "2026-11-25",
            "priority": "high",
            "overdue": True,
        },
        {
            "id": "b2",
            "title": "Revise normal forms",
            "due": "2026-11-27",
            "priority": None,
            "overdue": False,
        },
        {"id": "c3", "title": "Buy a notebook", "due": None, "priority": None, "overdue": False},
    ],
    "overdue": 1,
    "streak": 4,
    "countdown": {"label": "Semester exams", "date": "2026-12-07", "days": 11},
}
HEALTHY = {"type": "health", "ok": True, "checks": []}
SICK = {
    "type": "health",
    "ok": False,
    "checks": [{"name": "LLM", "status": "fail", "detail": "not reachable (run `ollama serve`)"}],
}

# (caption, events sent after connecting; None = the core never answers)
LOOKS = [
    ("offline", None),
    ("idle", [HEALTHY]),
    ("listening", [HEALTHY, {"type": "state", "state": "listening"}]),
    ("thinking", [HEALTHY, {"type": "state", "state": "thinking"}]),
    ("speaking", [HEALTHY, {"type": "state", "state": "speaking"}]),
    ("nudge", [HEALTHY, {"type": "nudge", "title": "Reminder", "text": "call mom"}]),
    ("focus", [HEALTHY, {"type": "focus", "on": True, "label": "DBMS"}]),
    ("unwell", [SICK]),
]

FAKE_CORE = """
(events) => {
  class FakeCore {
    constructor() {
      this.readyState = 0;
      if (events === null) return;  // offline: never opens
      setTimeout(() => {
        this.readyState = 1;
        this.onopen && this.onopen({});
        for (const e of events) this.onmessage && this.onmessage({ data: JSON.stringify(e) });
      }, 30);
    }
    send() {}
    close() {}
  }
  window.WebSocket = FakeCore;
}
"""


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def shoot(browser, url: str, events, size, path: Path) -> Image.Image:
    page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=2)
    page.add_init_script(f"({FAKE_CORE})({json.dumps(events)})")
    page.clock.set_fixed_time("2026-11-26T20:40:00")
    page.goto(url)
    page.wait_for_timeout(400)
    page.screenshot(path=str(path))
    page.close()
    return Image.open(path).convert("RGB")


def labelled(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGB", (image.width, image.height + 60), "#0b1016")
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=28)
    width = draw.textlength(text, font=font)
    draw.text(((image.width - width) / 2, image.height + 14), text, fill="#e2e8f0", font=font)
    return canvas


def main() -> None:
    if not (DIST / "index.html").is_file():
        raise SystemExit("build the page first: cd ui && npm run build")
    OUT.mkdir(parents=True, exist_ok=True)
    server, url = serve(DIST)
    tmp = OUT / "_frame.png"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            frames = []
            for name, events in LOOKS:
                ring = [DAY] if events else []
                image = shoot(
                    browser, url, None if events is None else ring + events, (200, 200), tmp
                )
                frames.append(labelled(image, name))
            deck_events = [
                HEALTHY,
                DAY,
                BRIEF,
                {"type": "transcript", "role": "you", "text": "what's next?"},
                {
                    "type": "transcript",
                    "role": "rosie",
                    "text": "DBMS until nine, then call mom at 21:30.",
                },
            ]
            deck = shoot(browser, url + "/#deck", deck_events, (380, 560), OUT / "deck.png")
            browser.close()
    finally:
        server.shutdown()
        tmp.unlink(missing_ok=True)

    strip = Image.new("RGB", (sum(f.width for f in frames), frames[0].height), "#0b1016")
    x = 0
    for frame in frames:
        strip.paste(frame, (x, 0))
        x += frame.width
    strip.save(OUT / "orb-looks.png")
    small = [f.resize((f.width // 2, f.height // 2)) for f in frames]
    small[0].save(OUT / "demo.gif", save_all=True, append_images=small[1:], duration=1200, loop=0)
    print(f"wrote demo.gif, orb-looks.png and deck.png ({deck.width}x{deck.height}) to {OUT}")


if __name__ == "__main__":
    main()
