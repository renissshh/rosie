"""Persisted scheduler: jobs in SQLite, run by a simple tick loop.

Rules (see docs/decisions/0002-own-scheduler.md):

    once                     run at `at`, then the job is removed
    daily@07:30              every day at 07:30 local time
    weekly:mon,wed,fri@18:00 those weekdays at 18:00
    every:90m                every 90 minutes

Times are stored in UTC and recurrence is computed in the user's zone (IST).
Missed runs (laptop off) are merged: the job runs once, then moves to its next
future time. A handler that crashes is logged and the job still moves on, so one
bad job can't block the others.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("rosie.scheduler")

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAILY = re.compile(r"daily@(\d{1,2}):(\d{2})")
_WEEKLY = re.compile(r"weekly:([a-z,]+)@(\d{1,2}):(\d{2})")
_EVERY = re.compile(r"every:(\d+)m")

Handler = Callable[["Job"], None]


class ScheduleError(ValueError):
    """A rule or time Rosie can't schedule."""


@dataclass(frozen=True)
class Job:
    id: str
    kind: str  # which handler runs it, e.g. "reminder"
    rule: str
    next_run: datetime  # UTC
    payload: dict[str, Any]


def _clock(h: str, m: str) -> time:
    hour, minute = int(h), int(m)
    if hour > 23 or minute > 59:
        raise ScheduleError(f"bad time {h}:{m}")
    return time(hour, minute)


def validate_rule(rule: str) -> None:
    if rule == "once":
        return
    if m := _DAILY.fullmatch(rule):
        _clock(m[1], m[2])
        return
    if m := _EVERY.fullmatch(rule):
        if int(m[1]) < 1:
            raise ScheduleError("every:Nm needs N >= 1")
        return
    if m := _WEEKLY.fullmatch(rule):
        if any(d not in DAYS for d in m[1].split(",")):
            raise ScheduleError(f"weekdays must be from {','.join(DAYS)}")
        _clock(m[2], m[3])
        return
    raise ScheduleError(
        f"unknown rule '{rule}' (once, daily@HH:MM, weekly:mon,fri@HH:MM, every:Nm)"
    )


def _utc(moment: datetime) -> datetime:
    """UTC, whole seconds: stored as text, so sorting the text sorts by time."""
    return moment.astimezone(UTC).replace(microsecond=0)


def next_after(rule: str, after: datetime, zone: ZoneInfo) -> datetime | None:
    """The first time strictly after `after` (UTC) that matches the rule, in UTC."""
    if rule == "once":
        return None
    if m := _EVERY.fullmatch(rule):
        return after + timedelta(minutes=int(m[1]))
    local = after.astimezone(zone)
    if m := _DAILY.fullmatch(rule):
        days, at = set(range(7)), _clock(m[1], m[2])
    elif m := _WEEKLY.fullmatch(rule):
        days, at = {DAYS.index(d) for d in m[1].split(",")}, _clock(m[2], m[3])
    else:
        raise ScheduleError(f"unknown rule '{rule}'")
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        candidate = datetime.combine(day, at, tzinfo=zone)
        if day.weekday() in days and candidate > local:
            return candidate.astimezone(UTC)
    raise ScheduleError(f"no next time for '{rule}'")  # pragma: no cover


class Scheduler:
    def __init__(
        self,
        db_path: Path,
        timezone: str = "Asia/Kolkata",
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.db_path = db_path
        self.zone = ZoneInfo(timezone)
        self.now = now
        self.handlers: dict[str, Handler] = {}
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, rule TEXT, "
                "next_run TEXT, payload TEXT)"
            )

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def on(self, kind: str, handler: Handler) -> None:
        self.handlers[kind] = handler

    def add(
        self,
        kind: str,
        rule: str = "once",
        at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Job:
        """Schedule a job. `at` is required for "once"; otherwise it defaults to the next match."""
        validate_rule(rule)
        if at is not None and at.tzinfo is None:
            raise ScheduleError("times must be timezone-aware")
        if at is None:
            if rule == "once":
                raise ScheduleError("a one-off job needs a time")
            at = next_after(rule, self.now(), self.zone)
        job = Job(uuid.uuid4().hex[:8], kind, rule, _utc(at), payload or {})
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
                (job.id, kind, rule, job.next_run.isoformat(), json.dumps(job.payload)),
            )
        return job

    def ensure_daily(self, kind: str, at: str) -> Job:
        """Exactly one daily job of this kind at HH:MM (safe to call on every start)."""
        rule = f"daily@{at}"
        existing = [j for j in self.jobs() if j.kind == kind]
        if [j.rule for j in existing] == [rule]:
            return existing[0]
        for job in existing:
            self.cancel(job.id)
        return self.add(kind, rule)

    def jobs(self) -> list[Job]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY next_run").fetchall()
        return [Job(i, k, r, datetime.fromisoformat(n), json.loads(p)) for i, k, r, n, p in rows]

    def get(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs() if j.id == job_id), None)

    def cancel(self, job_id: str) -> bool:
        with closing(self._connect()) as db, db:
            return db.execute("DELETE FROM jobs WHERE id = ?", (job_id,)).rowcount > 0

    def reschedule(self, job_id: str, at: datetime) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE jobs SET next_run = ? WHERE id = ?",
                (_utc(at).isoformat(), job_id),
            )

    def run_pending(self) -> list[Job]:
        """Run every job that is due now. Returns the jobs that ran."""
        now = self.now()
        ran = []
        for job in self.jobs():
            if job.next_run > now:
                break  # sorted by time: nothing later is due
            handler = self.handlers.get(job.kind)
            if handler is None:
                log.error("no handler for job kind %r; leaving job %s", job.kind, job.id)
                continue
            try:
                handler(job)
            except Exception:
                log.exception("job %s (%s) failed", job.id, job.kind)
            ran.append(job)
            if self.get(job.id) != job:
                continue  # the handler itself cancelled or rescheduled it (e.g. snooze)
            following = next_after(job.rule, now, self.zone)
            if following is None:
                self.cancel(job.id)
            else:
                self.reschedule(job.id, following)
        return ran

    def run_forever(self, stop: threading.Event, every_s: float = 20.0) -> None:
        """Tick until `stop` is set. Used by the long-running Rosie process."""
        while not stop.is_set():
            self.run_pending()
            stop.wait(every_s)
