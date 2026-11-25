"""Tasks in rosie-vault/tasks/tasks.md, in the Obsidian Tasks plugin format:

    - [ ] Revise DBMS normal forms ⏫ 📅 2026-12-12 ^a1b2c3
    - [x] Pay hostel fee 📅 2026-11-20 ✅ 2026-11-19 ^0c4d5e

⏫ high, 🔼 medium, 🔽 low priority; 📅 due date; ✅ date completed; ^id an
Obsidian block id. So the same file works in Obsidian (with or without that
plugin) and for Rosie. Lines without an id still count (id derived from text).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from rosie.tools import Tool, ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

TASKS_FILE = "tasks/tasks.md"
Priority = Literal["high", "medium", "low"]
PRIORITY_EMOJI: dict[str, str] = {"high": "⏫", "medium": "🔼", "low": "🔽"}
_EMOJI_PRIORITY = {v: k for k, v in PRIORITY_EMOJI.items()}
_RANK = {"high": 0, "medium": 1, None: 2, "low": 3}

_LINE = re.compile(r"^- \[(?P<done>[ xX])\] (?P<body>.*?)(?: \^(?P<id>[0-9a-f]{6}))?\s*$")
_DUE = re.compile(r"\s*📅\s*(\d{4}-\d{2}-\d{2})")
_DONE = re.compile(r"\s*✅\s*(\d{4}-\d{2}-\d{2})")
_PRIO = re.compile(r"\s*([⏫🔼🔽])")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class TaskError(ValueError):
    """Unknown task id, empty title or a due date Rosie can't read."""


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due: date | None = None
    priority: Priority | None = None
    done: bool = False
    done_on: date | None = None  # empty if ticked by hand in Obsidian without a date

    def line(self) -> str:
        parts = [f"- [{'x' if self.done else ' '}] {self.title}"]
        if self.priority:
            parts.append(PRIORITY_EMOJI[self.priority])
        if self.due:
            parts.append(f"📅 {self.due.isoformat()}")
        if self.done_on:
            parts.append(f"✅ {self.done_on.isoformat()}")
        parts.append(f"^{self.id}")
        return " ".join(parts)

    def show(self, today: date) -> str:
        bits = [f"[{self.id}]", self.title]
        if self.priority:
            bits.append(f"({self.priority})")
        if self.due:
            late = " OVERDUE" if not self.done and self.due < today else ""
            bits.append(f"due {self.due:%a %d %b}{late}")
        if self.done:
            bits.append(f"done {self.done_on:%d %b}" if self.done_on else "done")
        return " ".join(bits)


def parse_due(text: str, today: date) -> date:
    """'2026-12-12', 'today', 'tomorrow', 'friday' (next one), 'in 3 days', 'next week'."""
    t = text.strip().lower()
    if t == "today":
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    if t == "next week":
        return today + timedelta(days=7)
    if m := re.fullmatch(r"in (\d+) days?", t):
        return today + timedelta(days=int(m[1]))
    if t.removeprefix("next ") in _WEEKDAYS:
        ahead = (_WEEKDAYS.index(t.removeprefix("next ")) - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise TaskError(f"can't read due date '{text}'; use YYYY-MM-DD or 'tomorrow'") from None


def parse_line(line: str) -> Task | None:
    m = _LINE.match(line)
    if not m:
        return None
    body = m["body"]
    due = _DUE.search(body)
    done = _DONE.search(body)
    prio = _PRIO.search(body)
    title = _PRIO.sub("", _DONE.sub("", _DUE.sub("", body))).strip()
    return Task(
        id=m["id"] or hashlib.sha1(title.encode()).hexdigest()[:6],
        title=title,
        due=date.fromisoformat(due[1]) if due else None,
        priority=_EMOJI_PRIORITY.get(prio[1]) if prio else None,  # type: ignore[arg-type]
        done=m["done"] in "xX",
        done_on=date.fromisoformat(done[1]) if done else None,
    )


class TaskStore:
    def __init__(self, writer: VaultWriter, today: Callable[[], date] = date.today) -> None:
        self.writer = writer
        self.today = today

    def _lines(self) -> list[str]:
        path = self.writer.root / TASKS_FILE
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def all(self) -> list[Task]:
        return [t for line in self._lines() if (t := parse_line(line))]

    def get(self, task_id: str) -> Task:
        for task in self.all():
            if task.id == task_id:
                return task
        raise TaskError(f"no task with id {task_id}")

    def add(self, title: str, due: str | None = None, priority: Priority | None = None) -> Task:
        title = " ".join(title.split())
        if not title:
            raise TaskError("a task needs a title")
        if priority is not None and priority not in PRIORITY_EMOJI:
            raise TaskError("priority must be high, medium or low")
        taken = {t.id for t in self.all()}
        new_id = secrets.token_hex(3)
        while new_id in taken:
            new_id = secrets.token_hex(3)
        task = Task(new_id, title, parse_due(due, self.today()) if due else None, priority)
        lines = self._lines() or ["# tasks", ""]
        lines.append(task.line())
        self.writer.write(TASKS_FILE, "\n".join(lines) + "\n")
        return task

    def complete(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.done:
            return task
        finished = replace(task, done=True, done_on=self.today())
        lines = [
            finished.line() if (t := parse_line(line)) and t.id == task_id else line
            for line in self._lines()
        ]
        self.writer.write(TASKS_FILE, "\n".join(lines) + "\n")
        return finished

    def open_tasks(self) -> list[Task]:
        """Open tasks, most urgent first: by due date (none last), then priority."""
        return sorted(
            (t for t in self.all() if not t.done),
            key=lambda t: (t.due or date.max, _RANK[t.priority]),
        )

    def overdue(self) -> list[Task]:
        today = self.today()
        return [t for t in self.open_tasks() if t.due and t.due < today]


def register_task_tools(registry: ToolRegistry, store: TaskStore) -> None:
    """All three use the "tasks.manage" permission, which the owner set to allow."""

    def guarded(fn):
        def run(**kwargs):
            try:
                return fn(**kwargs)
            except TaskError as exc:
                raise ToolError(str(exc)) from None

        return run

    def list_tasks(status: str = "open") -> str:
        today = store.today()
        if status == "open":
            tasks = store.open_tasks()
        elif status == "overdue":
            tasks = store.overdue()
        else:
            tasks = [t for t in store.all() if t.done]
        return "\n".join(t.show(today) for t in tasks) or f"no {status} tasks"

    registry.register(
        Tool(
            "add_task",
            "Add a task to the user's list",
            guarded(
                lambda title, due=None, priority=None: store.add(title, due, priority).show(
                    store.today()
                )
            ),
            "personal",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due": {"type": "string", "description": "YYYY-MM-DD, today, tomorrow, friday"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title"],
            },
            action="tasks.manage",
        )
    )
    registry.register(
        Tool(
            "list_tasks",
            "List the user's tasks, most urgent first",
            list_tasks,
            "read",
            {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["open", "overdue", "done"]}},
            },
            action="tasks.manage",
        )
    )
    registry.register(
        Tool(
            "complete_task",
            "Mark a task as done",
            guarded(lambda id: store.complete(id).show(store.today())),
            "personal",
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            action="tasks.manage",
        )
    )
