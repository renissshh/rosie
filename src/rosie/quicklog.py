"""One-tap logging from the Command Deck, and the numbers its cards show.

    log study "DBMS normal forms 45m"  -> rosie-vault/study-log/2026-11-26.md
                                          - 19:40 DBMS normal forms (45 min)
    log gym "push day, bench 3x8 40kg" -> rosie-vault/training-log/2026-11-26.md
    log task "buy notebook"            -> a new task (tasks/tasks.md)

One note per day keeps the logs easy to read in Obsidian and makes the study streak
simple: a day counts if its study-log note has at least one entry. The Sprint 6
coaches read these same notes.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from rosie.config import Countdown
from rosie.tasks import TaskStore
from rosie.vault_writer import VaultWriter

LogKind = Literal["study", "gym", "task"]
_DURATION = re.compile(r"\s*\b(?:(\d+)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?\s*$")
MAX_TEXT = 300


class LogError(ValueError):
    """Nothing to log, or an unknown kind."""


def split_duration(text: str) -> tuple[str, int | None]:
    """'DBMS 1h 30m' -> ('DBMS', 90). The duration must be at the end; None if absent."""
    match = _DURATION.search(text)
    if match and (match.group(1) or match.group(2)):
        minutes = int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
        rest = text[: match.start()].strip(" ,-")
        if rest:
            return rest, minutes
    return text.strip(), None


def study_note(day: date) -> str:
    return f"study-log/{day:%Y-%m-%d}.md"


def training_note(day: date) -> str:
    return f"training-log/{day:%Y-%m-%d}.md"


@dataclass
class QuickLog:
    writer: VaultWriter
    tasks: TaskStore
    now: Callable[[], datetime]

    def log(self, kind: str, text: str) -> str:
        """Write the entry; returns a short confirmation for the deck."""
        text = " ".join(str(text).split())[:MAX_TEXT]
        if not text:
            raise LogError("type what you did first")
        now = self.now()
        if kind == "study":
            subject, minutes = split_duration(text)
            line = f"- {now:%H:%M} {subject}" + (f" ({minutes} min)" if minutes else "")
            self._append(study_note(now.date()), "Study", now, line)
            return f"Logged study: {subject}" + (f", {minutes} min" if minutes else "")
        if kind == "gym":
            self._append(training_note(now.date()), "Training", now, f"- {now:%H:%M} {text}")
            return f"Logged training: {text}"
        if kind == "task":
            task = self.tasks.add(text)
            return f"Added task: {task.title}"
        raise LogError(f"can't log {kind!r}: use study, gym or task")

    def _append(self, rel: str, title: str, now: datetime, line: str) -> None:
        exists = (self.writer.root / rel).is_file()
        head = "" if exists else f"# {title}, {now:%a %d %b %Y}\n\n"
        self.writer.append(rel, head + line + "\n")


def has_study(vault: Path, day: date) -> bool:
    note = vault / study_note(day)
    if not note.is_file():
        return False
    return any(line.startswith("- ") for line in note.read_text(encoding="utf-8").splitlines())


def study_streak(vault: Path, today: date, limit: int = 366) -> int:
    """Days in a row with a study entry. Today only counts once logged; until then the
    streak from yesterday still stands (the day isn't over yet)."""
    day = today if has_study(vault, today) else today - timedelta(days=1)
    streak = 0
    while streak < limit and has_study(vault, day):
        streak += 1
        day -= timedelta(days=1)
    return streak


def next_countdown(countdowns: list[Countdown], today: date) -> dict[str, Any] | None:
    ahead = [c for c in countdowns if c.date >= today]
    if not ahead:
        return None
    soonest = min(ahead, key=lambda c: c.date)
    return {
        "label": soonest.label,
        "date": soonest.date.isoformat(),
        "days": (soonest.date - today).days,
    }


def brief_event(tasks: TaskStore, vault: Path, countdowns: list[Countdown]) -> dict[str, Any]:
    """The Command Deck's cards: top 3 tasks, overdue count, study streak, countdown."""
    today = tasks.today()
    top = tasks.open_tasks()[:3]
    return {
        "type": "brief",
        "top3": [
            {
                "id": t.id,
                "title": t.title,
                "due": t.due.isoformat() if t.due else None,
                "priority": t.priority,
                "overdue": bool(t.due and t.due < today),
            }
            for t in top
        ],
        "overdue": len(tasks.overdue()),
        "streak": study_streak(vault, today),
        "countdown": next_countdown(countdowns, today),
    }


class DeckFeed:
    """Bridge handlers for the Command Deck (`log`, `done`) and its `brief` cards.

    `refresh()` sends the cards again only if they changed; it runs after every log,
    every chat answer (she may have added a task) and on the 30-second tick.
    """

    def __init__(self, bridge, quicklog: QuickLog, countdowns: list[Countdown]) -> None:
        self.bridge = bridge
        self.quicklog = quicklog
        self.countdowns = countdowns
        self._last: dict[str, Any] | None = None
        bridge.on("log", self.on_log)
        bridge.on("done", self.on_done)

    def refresh(self, *_: object) -> None:
        event = brief_event(self.quicklog.tasks, self.quicklog.writer.root, self.countdowns)
        if event != self._last:
            self._last = event
            self.bridge.emit(event, keep=True)

    def on_log(self, message: dict[str, Any]) -> dict[str, Any]:
        from rosie.bridge import BridgeError
        from rosie.tasks import TaskError

        try:
            text = self.quicklog.log(str(message.get("what", "")), str(message.get("text", "")))
        except (LogError, TaskError) as exc:
            raise BridgeError(str(exc)) from exc
        self.refresh()
        return {"type": "logged", "text": text}

    def on_done(self, message: dict[str, Any]) -> dict[str, Any]:
        from rosie.bridge import BridgeError
        from rosie.tasks import TaskError

        try:
            task = self.quicklog.tasks.complete(str(message.get("id", "")))
        except TaskError as exc:
            raise BridgeError(str(exc)) from exc
        self.refresh()
        return {"type": "logged", "text": f"Done: {task.title}"}
