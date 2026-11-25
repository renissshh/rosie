"""Facts Rosie remembers: markdown in rosie-vault, searchable through SQLite.

Source of truth is plain markdown, one file per topic, one fact per line:

    rosie-vault/memory/study.md
        # study
        - DBMS exam is on 12 Dec ^f3a9c1
        - Weak at normalisation ^0b72de

The `^f3a9c1` ending is an Obsidian block id, so each fact has a stable id and
can be linked from other notes. The user can edit or delete lines in Obsidian;
a line he adds without an id still counts (it gets an id derived from its text).

The SQLite file (D:\\Rosie\\index\\memory.db) is only an index for search. It is
rebuilt from the markdown after every change, so it can always be deleted safely.
Uses SQLite's FTS5 full-text search, with a plain LIKE search as a fallback.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from rosie.tools import Tool, ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

MEMORY_DIR = "memory"
_FACT_LINE = re.compile(r"^- (?P<text>.+?)(?: \^(?P<id>[0-9a-f]{6}))?\s*$")
_TOPIC = re.compile(r"[^a-z0-9]+")
_WORD = re.compile(r"\w+")


class FactError(ValueError):
    """Unknown fact id or an empty fact."""


@dataclass(frozen=True)
class Fact:
    id: str
    topic: str
    text: str

    def line(self) -> str:
        return f"- {self.text} ^{self.id}"


def slug(topic: str) -> str:
    """'Study Plan!' -> 'study-plan'; empty -> 'general'."""
    return _TOPIC.sub("-", topic.strip().lower()).strip("-") or "general"


def _clean(text: str) -> str:
    text = " ".join(text.split())  # one line, single spaces
    if not text:
        raise FactError("a fact can't be empty")
    return text


def _derived_id(topic: str, text: str) -> str:
    return hashlib.sha1(f"{topic}\n{text}".encode()).hexdigest()[:6]


class FactStore:
    def __init__(self, writer: VaultWriter, index_path: Path) -> None:
        self.writer = writer
        self.index_path = index_path
        self._fts: bool | None = None

    # ---- markdown --------------------------------------------------------
    def _rel(self, topic: str) -> str:
        return f"{MEMORY_DIR}/{topic}.md"

    def _lines(self, topic: str) -> list[str]:
        path = self.writer.root / MEMORY_DIR / f"{topic}.md"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def _parse(self, topic: str, lines: list[str]) -> list[tuple[int, Fact]]:
        facts = []
        for i, line in enumerate(lines):
            m = _FACT_LINE.match(line)
            if m:
                text = m["text"].strip()
                facts.append((i, Fact(m["id"] or _derived_id(topic, text), topic, text)))
        return facts

    def topics(self) -> list[str]:
        folder = self.writer.root / MEMORY_DIR
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.md") if p.stem.lower() != "readme")

    def all(self) -> list[Fact]:
        return [f for t in self.topics() for _, f in self._parse(t, self._lines(t))]

    def get(self, fact_id: str) -> Fact:
        for fact in self.all():
            if fact.id == fact_id:
                return fact
        raise FactError(f"no fact with id {fact_id}")

    def _save(self, topic: str, lines: list[str]) -> None:
        self.writer.write(self._rel(topic), "\n".join(lines) + "\n")
        self.reindex()

    # ---- remember / update / forget ---------------------------------------
    def remember(self, text: str, topic: str = "general") -> Fact:
        text, topic = _clean(text), slug(topic)
        lines = self._lines(topic) or [f"# {topic}", ""]
        for _, fact in self._parse(topic, lines):
            if fact.text.lower() == text.lower():
                return fact  # already known: no duplicate
        taken = {f.id for f in self.all()}
        new_id = secrets.token_hex(3)
        while new_id in taken:
            new_id = secrets.token_hex(3)
        fact = Fact(new_id, topic, text)
        lines.append(fact.line())
        self._save(topic, lines)
        return fact

    def update(self, fact_id: str, text: str) -> Fact:
        old = self.get(fact_id)
        new = Fact(fact_id, old.topic, _clean(text))
        lines = self._lines(old.topic)
        for i, fact in self._parse(old.topic, lines):
            if fact.id == fact_id:
                lines[i] = new.line()
        self._save(old.topic, lines)
        return new

    def forget(self, fact_id: str) -> Fact:
        """Remove the fact's line. It stays recoverable in rosie-vault's git history."""
        old = self.get(fact_id)
        lines = self._lines(old.topic)
        drop = {i for i, fact in self._parse(old.topic, lines) if fact.id == fact_id}
        self._save(old.topic, [line for i, line in enumerate(lines) if i not in drop])
        return old

    # ---- SQLite index ----------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.index_path)

    def reindex(self) -> int:
        """Rebuild the index from the markdown files. Returns the number of facts."""
        facts = self.all()
        with closing(self._connect()) as db, db:
            db.execute("DROP TABLE IF EXISTS facts")
            db.execute("DROP TABLE IF EXISTS facts_fts")
            db.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, topic TEXT, text TEXT)")
            db.executemany(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?)",
                [(f.id, f.topic, f.text) for f in facts],
            )
            try:
                db.execute("CREATE VIRTUAL TABLE facts_fts USING fts5(id UNINDEXED, topic, text)")
                db.execute("INSERT INTO facts_fts SELECT id, topic, text FROM facts")
                self._fts = True
            except sqlite3.OperationalError:  # SQLite built without FTS5
                self._fts = False
        return len(facts)

    def search(self, query: str, limit: int = 5) -> list[Fact]:
        """Facts matching any word of the query, best matches first."""
        words = [w.lower() for w in _WORD.findall(query) if len(w) > 1]
        if not words:
            return []
        if self._fts is None or not self.index_path.exists():
            self.reindex()
        with closing(self._connect()) as db:
            if self._fts:
                match = " OR ".join(f'"{w}"' for w in words)
                rows = db.execute(
                    "SELECT id, topic, text FROM facts_fts WHERE facts_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (match, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT id, topic, text FROM facts").fetchall()
                scored = [(sum(w in f"{r[1]} {r[2]}".lower() for w in words), r) for r in rows]
                rows = [r for s, r in sorted(scored, key=lambda x: -x[0]) if s][:limit]
        return [Fact(*row) for row in rows]


def register_memory_tools(registry: ToolRegistry, store: FactStore) -> None:
    """Tools for the agent. Writing needs the "memory.write" permission (ask until decided);
    forgetting is deleting Rosie's own note, which the owner allowed (vault.rosie.delete)."""

    def guarded(fn):
        def run(**kwargs):
            try:
                return fn(**kwargs)
            except FactError as exc:
                raise ToolError(str(exc)) from None

        return run

    text_param = {"type": "string", "description": "The fact, as one short sentence"}
    id_param = {"type": "string", "description": "The 6-character fact id"}

    registry.register(
        Tool(
            "remember_fact",
            "Remember a fact about the user for later",
            guarded(lambda text, topic="general": _show(store.remember(text, topic))),
            "personal",
            {
                "type": "object",
                "properties": {
                    "text": text_param,
                    "topic": {"type": "string", "description": "e.g. study, training, life"},
                },
                "required": ["text"],
            },
            action="memory.write",
        )
    )
    registry.register(
        Tool(
            "update_fact",
            "Correct a fact Rosie remembers",
            guarded(lambda id, text: _show(store.update(id, text))),
            "personal",
            {
                "type": "object",
                "properties": {"id": id_param, "text": text_param},
                "required": ["id", "text"],
            },
            action="memory.write",
        )
    )
    registry.register(
        Tool(
            "forget_fact",
            "Forget a fact Rosie remembers",
            guarded(lambda id: "forgot " + _show(store.forget(id))),
            "personal",
            {"type": "object", "properties": {"id": id_param}, "required": ["id"]},
            action="vault.rosie.delete",
        )
    )
    registry.register(
        Tool(
            "recall_facts",
            "Search the facts Rosie remembers about the user",
            lambda query: "\n".join(_show(f) for f in store.search(query, 8)) or "nothing found",
            "read",
            {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    )


def _show(fact: Fact) -> str:
    return f"[{fact.id}] ({fact.topic}) {fact.text}"
