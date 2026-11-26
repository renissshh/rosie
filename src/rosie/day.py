"""Today, as the orb's Day Ring draws it: blocks of the usual day plus timed marks.

    blocks  from `day_blocks` in rosie.yaml (study, college, gym ...), for today's weekday
    marks   today's reminders, the morning brief and the nightly review (scheduler jobs)

`DayWatcher.tick(now)` runs every half minute inside `rosie serve`. It sends a new
`day` event when anything on the ring changed (a reminder was added, the date rolled
over) and a `focus` event when a study block starts or ends, so the orb dims during
study and only urgent reminders get through. Plain code, no LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from rosie.brief import BRIEF_JOB
from rosie.config import WEEKDAYS, DayBlock
from rosie.reminders import REMINDER
from rosie.review import REVIEW_JOB
from rosie.scheduler import Job

Event = dict[str, Any]
FOCUS_KINDS = {"study"}
_MARK_KINDS = {REMINDER: "reminder", BRIEF_JOB: "brief", REVIEW_JOB: "review"}
_MARK_TEXT = {BRIEF_JOB: "Morning brief", REVIEW_JOB: "Nightly review"}


def _minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


def blocks_for(blocks: list[DayBlock], day: date) -> list[DayBlock]:
    """The blocks that happen on this weekday, in time order."""
    weekday = WEEKDAYS[day.weekday()]
    return sorted((b for b in blocks if weekday in b.days), key=lambda b: _minutes(b.start))


def marks_for(jobs: list[Job], day: date, zone: ZoneInfo) -> list[Event]:
    """Today's timed events from the scheduler, as dots on the ring."""
    marks = []
    for job in jobs:
        kind = _MARK_KINDS.get(job.kind)
        local = job.next_run.astimezone(zone)
        if kind is None or local.date() != day:
            continue
        text = job.payload.get("text") or _MARK_TEXT.get(job.kind, kind)
        marks.append({"at": f"{local:%H:%M}", "kind": kind, "text": text})
    return sorted(marks, key=lambda m: m["at"])


def day_event(blocks: list[DayBlock], jobs: list[Job], now: datetime) -> Event:
    today = now.date()
    return {
        "type": "day",
        "date": today.isoformat(),
        "blocks": [
            {"start": b.start, "end": b.end, "kind": b.kind, "label": b.label or b.kind.title()}
            for b in blocks_for(blocks, today)
        ],
        "marks": marks_for(jobs, today, now.tzinfo),  # type: ignore[arg-type]
    }


def focus_block(blocks: list[DayBlock], now: datetime) -> DayBlock | None:
    """The study block happening right now, if any.

    A block that crosses midnight (19:00 -> 01:00) belongs to the day it started on,
    so at 00:30 on Tuesday it is Monday's block that counts.
    """
    mins = now.hour * 60 + now.minute
    yesterday = date.fromordinal(now.date().toordinal() - 1)
    for block in blocks_for(blocks, now.date()):
        start, end = _minutes(block.start), _minutes(block.end)
        inside = start <= mins < end if start <= end else mins >= start
        if block.kind in FOCUS_KINDS and inside:
            return block
    for block in blocks_for(blocks, yesterday):
        start, end = _minutes(block.start), _minutes(block.end)
        if block.kind in FOCUS_KINDS and start > end and mins < end:
            return block
    return None


class DayWatcher:
    def __init__(
        self,
        blocks: list[DayBlock],
        jobs: Callable[[], list[Job]],
        emit: Callable[..., None],
    ) -> None:
        self.blocks = blocks
        self.jobs = jobs
        self.emit = emit
        self._last_day: Event | None = None
        self._focus: str | None = None  # label of the focus block we're in

    def tick(self, now: datetime) -> list[Event]:
        """Send what changed since the last tick; returns the events sent."""
        sent = []
        day = day_event(self.blocks, self.jobs(), now)
        if day != self._last_day:
            self._last_day = day
            sent.append(day)
        block = focus_block(self.blocks, now)
        label = (block.label or block.kind.title()) if block else None
        if label != self._focus:
            self._focus = label
            sent.append({"type": "focus", "on": label is not None, "label": label or ""})
        for event in sent:
            self.emit(event, keep=True)
        return sent


def watch_forever(watcher: DayWatcher, now: Callable[[], datetime], stop, every_s: float = 30.0):
    """Tick until `stop` (a threading.Event) is set. Used by `rosie serve` in a thread."""
    while not stop.is_set():
        watcher.tick(now())
        stop.wait(every_s)
