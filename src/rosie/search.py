"""Full-text search across both vaults: the user's (read only) and rosie-vault.

The index is a SQLite FTS5 file (D:\\Rosie\\index\\notes.db), never anything inside
either vault. `refresh()` re-reads only notes whose size or modified time changed
and drops notes that were deleted, so it is cheap to call before every search.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rosie.tools import Tool, ToolRegistry

VaultName = Literal["yours", "rosie"]
SKIP_DIRS = {".obsidian", ".trash", ".git"}
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class Hit:
    vault: VaultName
    path: str
    snippet: str

    def show(self) -> str:
        return f"[{self.vault}] {self.path}: {self.snippet}"


def iter_notes(root: Path) -> Iterator[Path]:
    """Markdown notes under root, skipping app folders and anything resolving outside."""
    base = root.resolve()
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.is_file() and path.resolve().is_relative_to(base):
            yield path


class NoteIndex:
    def __init__(self, index_path: Path, vaults: dict[VaultName, Path]) -> None:
        self.index_path = index_path
        self.vaults = vaults

    def _connect(self) -> sqlite3.Connection:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.index_path)
        db.execute(
            "CREATE TABLE IF NOT EXISTS files "
            "(vault TEXT, path TEXT, size INTEGER, mtime INTEGER, PRIMARY KEY (vault, path))"
        )
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes "
            "USING fts5(vault UNINDEXED, path UNINDEXED, title, body)"
        )
        return db

    def refresh(self) -> int:
        """Bring the index up to date. Returns how many notes were (re)indexed."""
        changed = 0
        with closing(self._connect()) as db, db:
            for vault, root in self.vaults.items():
                known = {
                    path: (size, mtime)
                    for path, size, mtime in db.execute(
                        "SELECT path, size, mtime FROM files WHERE vault = ?", (vault,)
                    )
                }
                seen = set()
                for note in iter_notes(root) if root.is_dir() else ():
                    rel = note.relative_to(root).as_posix()
                    seen.add(rel)
                    stat = note.stat()
                    if known.get(rel) == (stat.st_size, stat.st_mtime_ns):
                        continue
                    body = note.read_text(encoding="utf-8", errors="replace")
                    self._remove(db, vault, rel)
                    db.execute(
                        "INSERT INTO notes VALUES (?, ?, ?, ?)", (vault, rel, note.stem, body)
                    )
                    db.execute(
                        "INSERT INTO files VALUES (?, ?, ?, ?)",
                        (vault, rel, stat.st_size, stat.st_mtime_ns),
                    )
                    changed += 1
                for rel in set(known) - seen:
                    self._remove(db, vault, rel)
        return changed

    @staticmethod
    def _remove(db: sqlite3.Connection, vault: str, rel: str) -> None:
        db.execute("DELETE FROM notes WHERE vault = ? AND path = ?", (vault, rel))
        db.execute("DELETE FROM files WHERE vault = ? AND path = ?", (vault, rel))

    def search(self, query: str, limit: int = 5, vault: VaultName | None = None) -> list[Hit]:
        words = [w for w in _WORD.findall(query.lower()) if len(w) > 1]
        if not words:
            return []
        self.refresh()
        match = " OR ".join(f'"{w}"' for w in words)
        sql = (
            "SELECT vault, path, snippet(notes, 3, '**', '**', ' ... ', 12) FROM notes "
            "WHERE notes MATCH ?"
        )
        args: list = [match]
        if vault is not None:
            sql += " AND vault = ?"
            args.append(vault)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        with closing(self._connect()) as db:
            rows = db.execute(sql, args).fetchall()
        return [Hit(v, p, " ".join(s.split())) for v, p, s in rows]


def register_search_tool(registry: ToolRegistry, index: NoteIndex) -> None:
    def search_notes(query: str, vault: str = "both") -> str:
        which = None if vault == "both" else vault
        hits = index.search(query, limit=6, vault=which)  # type: ignore[arg-type]
        return "\n".join(h.show() for h in hits) or "no notes match"

    registry.register(
        Tool(
            "search_notes",
            "Search the user's Obsidian vault and Rosie's own vault by words",
            search_notes,
            "read",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "vault": {"type": "string", "enum": ["both", "yours", "rosie"]},
                },
                "required": ["query"],
            },
            action="vault.user.read",
        )
    )
