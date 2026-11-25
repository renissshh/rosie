"""System prompt builder.

Rosie's personality lives in a plain markdown file, `SOUL.md`, so it can be edited
without touching code (idea from Hermes Agent, see CREDITS.md). The prompt is:

    SOUL.md  +  current date/time  +  relevant memories/tasks  +  the tools she has

Lookup order for SOUL.md: `<data_dir>/SOUL.md` (the user's own edit, e.g.
D:\\Rosie\\SOUL.md), then the repo's `config/SOUL.md`, then a one-line fallback.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_SOUL = Path(__file__).resolve().parents[2] / "config" / "SOUL.md"
FALLBACK_SOUL = "You are Rosie, a concise and helpful personal assistant for VinsmokE."
MAX_SOUL_CHARS = 8_000  # keeps small local models from drowning in persona text


def load_soul(data_dir: Path | None = None, repo_soul: Path = REPO_SOUL) -> str:
    candidates = ([data_dir / "SOUL.md"] if data_dir is not None else []) + [repo_soul]
    for path in candidates:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text[:MAX_SOUL_CHARS]
    return FALLBACK_SOUL


def format_now(now: datetime) -> str:
    """e.g. 'Wednesday 25 Nov 2026, 23:45 IST (Asia/Kolkata)'."""
    zone = getattr(now.tzinfo, "key", None) or now.tzname() or "local"
    return f"{now:%A} {now.day} {now:%b %Y, %H:%M} {now.tzname()} ({zone})"


def build_system_prompt(
    soul: str,
    now: datetime,
    tool_names: Iterable[str] = (),
    context: str = "",
) -> str:
    parts = [soul.strip(), f"## Right now\nIt is {format_now(now)}."]
    if context.strip():
        parts.append(context.strip())
    names = list(tool_names)
    if names:
        parts.append("## Tools available\n" + ", ".join(names))
    else:
        parts.append("## Tools available\nNone yet. Answer from the conversation only.")
    return "\n\n".join(parts)


def now_in(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone))
