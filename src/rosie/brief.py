"""Morning brief: what matters today, built from tasks and reminders (no LLM needed).

    # Morning brief, Thu 26 Nov
    ## Top 3
    1. Revise DBMS normal forms (high), due Fri 27 Nov
    ## Today
    - 18:00 gym
    ## Overdue
    - Submit DBMS assignment, due Wed 25 Nov
    ## Avoiding?
    - "Clean desk" has been open for 9 days. 10 minutes on it today?

It is written to today's daily note in rosie-vault and a short version is sent as
a notification. Being plain code, it works even when Ollama is down.
"""

from __future__ import annotations

from datetime import date

from rosie.reminders import REMINDER, Reminders
from rosie.tasks import Task, TaskStore
from rosie.vault_writer import VaultWriter

AVOIDED_AFTER_DAYS = 3
BRIEF_JOB = "morning_brief"


def _task(t: Task) -> str:
    bits = [t.title]
    if t.priority:
        bits.append(f"({t.priority})")
    text = " ".join(bits)
    return f"{text}, due {t.due:%a %d %b}" if t.due else text


def avoided_task(tasks: list[Task], today: date, skip: set[str]) -> Task | None:
    """The open task created longest ago (at least 3 days), not already in the Top 3."""
    old = [
        t
        for t in tasks
        if t.id not in skip and t.created and (today - t.created).days >= AVOIDED_AFTER_DAYS
    ]
    return min(old, key=lambda t: t.created, default=None)  # type: ignore[arg-type]


def build_brief(tasks: TaskStore, reminders: Reminders | None = None) -> str:
    today = tasks.today()
    open_tasks = tasks.open_tasks()
    top = open_tasks[:3]
    lines = [f"# Morning brief, {today:%a %d %b}", "", "## Top 3"]
    lines += [f"{i}. {_task(t)}" for i, t in enumerate(top, 1)] or ["Nothing on the list. Add one?"]

    if reminders is not None:
        todays = [
            (j.next_run.astimezone(reminders.zone), j.payload["text"])
            for j in reminders.scheduler.jobs()
            if j.kind == REMINDER and j.next_run.astimezone(reminders.zone).date() == today
        ]
        if todays:
            lines += ["", "## Today"] + [f"- {at:%H:%M} {text}" for at, text in sorted(todays)]

    overdue = [t for t in open_tasks if t.due and t.due < today]
    if overdue:
        lines += ["", "## Overdue"] + [f"- {_task(t)}" for t in overdue]

    avoided = avoided_task(open_tasks, today, {t.id for t in top})
    if avoided:
        days = (today - avoided.created).days  # type: ignore[operator]
        lines += [
            "",
            "## Avoiding?",
            f'- "{avoided.title}" has been open for {days} days. 10 minutes on it today?',
        ]
    return "\n".join(lines) + "\n"


def short_brief(tasks: TaskStore) -> str:
    """One notification-sized line."""
    top = tasks.open_tasks()[:3]
    overdue = len(tasks.overdue())
    head = "Top 3: " + "; ".join(t.title for t in top) if top else "Nothing on your list."
    return head + (f" ({overdue} overdue)" if overdue else "")


class MorningBrief:
    """Scheduler handler: write the brief to the daily note and notify."""

    def __init__(self, tasks: TaskStore, writer: VaultWriter, notify, reminders=None) -> None:
        self.tasks = tasks
        self.writer = writer
        self.notify = notify
        self.reminders = reminders

    def run(self, job=None) -> str:
        text = build_brief(self.tasks, self.reminders)
        self.writer.append(f"daily/{self.tasks.today():%Y-%m-%d}.md", text)
        self.notify("Good morning", short_brief(self.tasks))
        return text

    def schedule(self, at: str = "07:30") -> None:
        """Make sure exactly one daily brief job exists (idempotent across restarts)."""
        if self.reminders is None:
            raise ValueError("scheduling the brief needs the reminders scheduler")
        self.reminders.scheduler.on(BRIEF_JOB, self.run)
        self.reminders.scheduler.ensure_daily(BRIEF_JOB, at)
