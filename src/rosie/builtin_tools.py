"""Rosie's first tools: the clock and reading a note from the user's own vault.

`read_note` is strictly read only and cannot leave the vault: the path is
resolved (which also follows symlinks) and must stay inside the vault folder.
Only markdown notes are read; Obsidian's own folders (.obsidian, .trash) are skipped.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rosie.config import RosieConfig
from rosie.prompt import format_now
from rosie.tools import ToolError, ToolRegistry

MAX_NOTE_CHARS = 12_000  # about 3k tokens: enough for a note, safe for an 8B model
_SKIP_DIRS = {".obsidian", ".trash", ".git"}


def get_datetime(timezone: str, now: Callable[[ZoneInfo], datetime] | None = None) -> str:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ToolError(f"unknown time zone '{timezone}'") from None
    moment = now(zone) if now else datetime.now(zone)
    return f"{format_now(moment)}; ISO {moment.isoformat(timespec='seconds')}"


class UserVault:
    """Read-only view of the user's Obsidian vault."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _inside(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.root)

    def notes(self) -> list[Path]:
        found = []
        for path in self.root.rglob("*.md"):
            rel = path.relative_to(self.root)
            if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
                continue
            if self._inside(path):
                found.append(path)
        return sorted(found)

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def find(self, name: str) -> Path:
        """Find a note by vault path ("Sem 3/DBMS.md", "Sem 3/DBMS") or by name ("DBMS")."""
        name = name.strip().replace("\\", "/")
        if not name:
            raise ToolError("give a note name or path")
        if Path(name).is_absolute() or ":" in name:
            raise ToolError("use a path inside your vault, not an absolute path")
        wanted = Path(name) if name.lower().endswith(".md") else Path(name + ".md")

        direct = self.root / wanted
        if direct.exists():
            if not self._inside(direct):
                raise ToolError(f"'{name}' is outside your vault")
            if direct.is_file():
                return direct

        stem = wanted.stem.lower()
        notes = self.notes()
        matches = [p for p in notes if p.stem.lower() == stem]
        if len(matches) == 1:
            return matches[0]
        if matches:
            options = ", ".join(self.rel(p) for p in matches[:10])
            raise ToolError(f"several notes are called '{wanted.stem}': {options}")
        stems = {p.stem: p for p in notes}
        close = difflib.get_close_matches(wanted.stem, stems, n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(self.rel(stems[c]) for c in close)}?" if close else ""
        raise ToolError(f"no note called '{name}' in your vault.{hint}")

    def read(self, name: str) -> str:
        path = self.find(name)
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_NOTE_CHARS:
            text = text[:MAX_NOTE_CHARS] + "\n\n[... note truncated]"
        return f"# {self.rel(path)}\n\n{text}"


def register_builtin_tools(registry: ToolRegistry, config: RosieConfig) -> None:
    @registry.tool(
        "get_datetime",
        "Get the current date, day and time. Use for 'what time/day is it' and date maths.",
    )
    def _get_datetime() -> str:
        return get_datetime(config.timezone)

    @registry.tool(
        "read_note",
        "Read a note from the user's own Obsidian vault (read only).",
        tier="read",
        action="vault.user.read",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Note name like 'DBMS' or a vault path like 'Sem 3/DBMS.md'",
                }
            },
            "required": ["name"],
        },
    )
    def _read_note(name: str) -> str:
        if config.user_vault_dir is None:
            raise ToolError("your vault isn't set up yet: add user_vault_dir to rosie.yaml")
        if not config.user_vault_dir.is_dir():
            raise ToolError(f"your vault folder {config.user_vault_dir} doesn't exist")
        return UserVault(config.user_vault_dir).read(name)
