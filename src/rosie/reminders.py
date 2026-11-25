"""Reminders on top of the scheduler.

Flow for every reminder that fires:

    reminder        -> notify "DBMS revision"            (+ follow-up in 15 min)
    follow-up       -> notify "Still pending: ..."       (+ skip check in 15 min)
    skip check      -> write "- 21:30 skipped: ..." to today's daily note

Saying done (`ack`) or snoozing at any point cancels the pending follow-up/skip.
So Rosie nudges once more, then stops nagging and just records it, which feeds the
nightly review later. Recurring reminders keep their schedule either way.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rosie.scheduler import DAYS, Job, Scheduler
from rosie.tools import Tool, ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

FOLLOW_UP = timedelta(minutes=15)
REMINDER, FOLLOW, SKIP = "reminder", "reminder_followup", "reminder_skip"
Notify = Callable[[str, str], None]  # (title, text)

_REPEATS = {
    "daily": "daily",
    "weekdays": "weekly:mon,tue,wed,thu,fri",
    "weekends": "weekly:sat,sun",
}


class ReminderError(ValueError):
    """A time or repeat Rosie can't read."""


def parse_when(text: str, now: datetime) -> datetime:
    """'21:30', 'tomorrow 7:30', 'in 20 minutes', 'in 2 hours', '2026-12-12 09:00'.

    A bare time that already passed today means tomorrow. `now` is local and aware.
    """
    t = text.strip().lower()
    if m := re.fullmatch(r"in (\d+) (minute|min|hour|hr)s?", t):
        unit = "hours" if m[2] in {"hour", "hr"} else "minutes"
        return now + timedelta(**{unit: int(m[1])})
    day = now.date()
    if t.startswith("tomorrow"):
        day, t = day + timedelta(days=1), t.removeprefix("tomorrow").strip()
    elif t.startswith("today"):
        t = t.removeprefix("today").strip()
    elif m := re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+(.+)", t):
        try:
            day = datetime.fromisoformat(m[1]).date()
        except ValueError:
            raise ReminderError(f"bad date in '{text}'") from None
        t = m[2]
    m = re.fullmatch(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        raise ReminderError(f"can't read '{text}'; try '21:30', 'tomorrow 7am' or 'in 20 minutes'")
    hour, minute = int(m[1]), int(m[2] or 0)
    if m[3] == "pm" and hour < 12:
        hour += 12
    if m[3] == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ReminderError(f"bad time in '{text}'")
    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
    if moment <= now and day == now.date() and not text.strip().lower().startswith("today"):
        moment += timedelta(days=1)
    return moment


def repeat_rule(repeat: str | None, at: datetime) -> str:
    """'daily' / 'weekdays' / 'weekends' / 'mon,thu' -> a scheduler rule at that time."""
    if not repeat or repeat == "once":
        return "once"
    hhmm = f"{at:%H:%M}"
    r = repeat.strip().lower().replace(" ", "")
    if r in _REPEATS:
        return f"{_REPEATS[r]}@{hhmm}"
    days = [d[:3] for d in r.split(",")]
    if days and all(d in DAYS for d in days):
        return f"weekly:{','.join(days)}@{hhmm}"
    raise ReminderError(f"can't repeat '{repeat}'; use daily, weekdays, weekends or mon,thu")


class Reminders:
    def __init__(
        self,
        scheduler: Scheduler,
        notify: Notify,
        writer: VaultWriter,
        timezone: str = "Asia/Kolkata",
    ) -> None:
        self.scheduler = scheduler
        self.notify = notify
        self.writer = writer
        self.zone = ZoneInfo(timezone)
        scheduler.on(REMINDER, self._fire)
        scheduler.on(FOLLOW, self._follow_up)
        scheduler.on(SKIP, self._skip)

    def now(self) -> datetime:
        return self.scheduler.now().astimezone(self.zone)

    # ---- user actions ------------------------------------------------------
    def remind(self, text: str, at: datetime, repeat: str | None = None) -> Job:
        text = " ".join(text.split())
        if not text:
            raise ReminderError("what should I remind you about?")
        return self.scheduler.add(REMINDER, repeat_rule(repeat, at), at, {"text": text})

    def upcoming(self) -> list[Job]:
        return [j for j in self.scheduler.jobs() if j.kind == REMINDER]

    def ack(self, reminder_id: str) -> bool:
        """He did it: stop the follow-up and skip check. True if anything was pending."""
        pending = [
            j
            for j in self.scheduler.jobs()
            if j.kind in {FOLLOW, SKIP} and j.payload.get("reminder_id") == reminder_id
        ]
        for job in pending:
            self.scheduler.cancel(job.id)
        return bool(pending)

    def snooze(self, reminder_id: str, minutes: int = 10) -> Job:
        text = self._text_of(reminder_id)
        self.ack(reminder_id)
        at = self.now() + timedelta(minutes=minutes)
        return self.scheduler.add(REMINDER, "once", at, {"text": text, "snoozed": reminder_id})

    def cancel(self, reminder_id: str) -> bool:
        self.ack(reminder_id)
        return self.scheduler.cancel(reminder_id)

    def _text_of(self, reminder_id: str) -> str:
        for job in self.scheduler.jobs():
            if job.id == reminder_id or job.payload.get("reminder_id") == reminder_id:
                return job.payload["text"]
        raise ReminderError(f"no reminder {reminder_id}")

    # ---- scheduler handlers ------------------------------------------------
    def _fire(self, job: Job) -> None:
        self.notify("Rosie", job.payload["text"])
        self._chain(FOLLOW, job)

    def _follow_up(self, job: Job) -> None:
        self.notify("Rosie", f"Still pending: {job.payload['text']}")
        self._chain(SKIP, job)

    def _skip(self, job: Job) -> None:
        now = self.now()
        self.writer.append(
            f"daily/{now:%Y-%m-%d}.md", f"- {now:%H:%M} skipped: {job.payload['text']}\n"
        )

    def _chain(self, kind: str, job: Job) -> None:
        reminder_id = job.payload.get("reminder_id", job.id)
        self.scheduler.add(
            kind,
            "once",
            self.now() + FOLLOW_UP,
            {"text": job.payload["text"], "reminder_id": reminder_id},
        )


def register_reminder_tools(registry: ToolRegistry, reminders: Reminders) -> None:
    """Reminders count as "tasks.manage" (decision 0001: manage tasks and reminders)."""

    def guarded(fn):
        def run(**kwargs):
            try:
                return fn(**kwargs)
            except (ReminderError, ValueError) as exc:
                raise ToolError(str(exc)) from None

        return run

    def show(job: Job) -> str:
        at = job.next_run.astimezone(reminders.zone)
        repeat = "" if job.rule == "once" else f" (repeats: {job.rule})"
        return f"[{job.id}] {at:%a %d %b %H:%M}: {job.payload['text']}{repeat}"

    def set_reminder(text: str, when: str, repeat: str = "once") -> str:
        return "set " + show(reminders.remind(text, parse_when(when, reminders.now()), repeat))

    def snooze(id: str, minutes: int = 10) -> str:
        return "snoozed to " + show(reminders.snooze(id, minutes))

    params = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "when": {"type": "string", "description": "21:30, tomorrow 7am, in 20 minutes"},
            "repeat": {"type": "string", "description": "once, daily, weekdays, mon,thu"},
        },
        "required": ["text", "when"],
    }
    id_only = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    tools = (
        Tool("set_reminder", "Set a reminder", guarded(set_reminder), "personal", params),
        Tool(
            "list_reminders",
            "List upcoming reminders",
            lambda: "\n".join(show(j) for j in reminders.upcoming()) or "no reminders",
        ),
        Tool(
            "reminder_done",
            "Mark a reminder as done so Rosie stops following up",
            lambda id: "done" if reminders.ack(id) else "nothing was pending",
            "personal",
            id_only,
        ),
        Tool(
            "snooze_reminder",
            "Snooze a reminder for some minutes",
            guarded(snooze),
            "personal",
            {
                "type": "object",
                "properties": {"id": {"type": "string"}, "minutes": {"type": "integer"}},
                "required": ["id"],
            },
        ),
        Tool(
            "cancel_reminder",
            "Cancel a reminder",
            lambda id: "cancelled" if reminders.cancel(id) else "no such reminder",
            "personal",
            id_only,
        ),
    )
    for tool in tools:
        registry.register(replace(tool, action="tasks.manage"))
