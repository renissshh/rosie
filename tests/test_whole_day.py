"""A whole day of Rosie in about a second: everything on a clock, wired like `rosie serve`.

`build_schedule` is the same wiring the real core starts (reminders, morning brief,
nightly review, vault backups); here the clock is fake and the test turns it, minute
by minute, the way the scheduler thread's tick would. This catches what unit tests of
each piece can't: jobs that collide, run twice, or never run once they're together.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import rosie.__main__ as cli
from rosie.config import RosieConfig
from rosie.scheduler import Scheduler

IST = ZoneInfo("Asia/Kolkata")


class Clock:
    def __init__(self, start: datetime) -> None:
        self.at = start.astimezone(UTC)

    def __call__(self) -> datetime:
        return self.at

    def local(self) -> datetime:
        return self.at.astimezone(IST)


@pytest.fixture
def day(tmp_path: Path, monkeypatch):
    """Friday 4 Dec 2026, 06:00 IST, a fresh data folder. Returns a small harness."""
    clock = Clock(datetime(2026, 12, 4, 6, 0, tzinfo=IST))
    # Dates in task due-checks, daily-note names and backup names come from now_in.
    monkeypatch.setattr(cli, "now_in", lambda tz: clock().astimezone(ZoneInfo(tz)))
    sent: list[tuple[str, str, str]] = []  # (local HH:MM, title, text)

    def notify(title: str, text: str) -> None:
        sent.append((f"{clock.local():%H:%M}", title, text))

    class Day:
        def __init__(self) -> None:
            self.clock = clock
            self.sent = sent
            self.config = RosieConfig(data_dir=tmp_path)
            self.reminders = self.start()

        def start(self, **changes):
            config = self.config.model_copy(update=changes)
            return cli.build_schedule(config, notify, now=clock)

        def run_until(self, hh_mm: str, next_day: bool = False, step_min: int = 1) -> None:
            h, m = map(int, hh_mm.split(":"))
            end = clock.local().replace(hour=h, minute=m)
            if next_day:
                end += timedelta(days=1)
            while clock.at < end.astimezone(UTC):
                clock.at = min(clock.at + timedelta(minutes=step_min), end.astimezone(UTC))
                self.reminders.scheduler.run_pending()

        def jump_to(self, hh_mm: str) -> None:
            """The laptop slept: one tick, a long time later."""
            h, m = map(int, hh_mm.split(":"))
            clock.at = clock.local().replace(hour=h, minute=m).astimezone(UTC)
            self.reminders.scheduler.run_pending()

        def note(self, date: str) -> str:
            path = self.config.vault_dir / "daily" / f"{date}.md"
            return path.read_text(encoding="utf-8") if path.is_file() else ""

        def at(self, title_or_text: str) -> list[str]:
            return [t for t, title, text in sent if title_or_text in (title, text)]

    harness = Day()
    cli.task_store(harness.config).add("Submit DBMS assignment", "2026-12-03", "high")
    return harness


def remind(day, text: str, hh_mm: str) -> None:
    h, m = map(int, hh_mm.split(":"))
    day.reminders.remind(text, day.clock.local().replace(hour=h, minute=m))


def test_a_normal_day(day) -> None:
    remind(day, "call mom", "21:30")
    day.run_until("06:00", next_day=True)

    # 07:30 brief: notification plus the full brief in today's daily note
    assert day.at("Good morning") == ["07:30"]
    morning = [text for t, title, text in day.sent if title == "Good morning"][0]
    assert "overdue" in morning
    assert "Submit DBMS assignment" in day.note("2026-12-04")

    # 21:30 reminder, 21:45 follow-up, 22:00 skipped in the daily note (never acked)
    assert day.at("call mom") == ["21:30"]
    assert day.at("Still pending: call mom") == ["21:45"]
    assert "22:00 skipped: call mom" in day.note("2026-12-04")

    # 22:00 nightly review nudge (no Telegram here)
    assert len([t for t, _, text in day.sent if "nightly review" in text]) == 1

    # 03:00 backup, named after the day it runs
    backups = sorted(p.name for p in (day.config.data_dir / "backups").glob("*.zip"))
    assert backups == ["rosie-vault-2026-12-05.zip"]

    # and nothing else talked: brief, reminder, follow-up, review
    assert len(day.sent) == 4


def test_acked_reminder_is_not_chased(day) -> None:
    remind(day, "drink water", "10:00")
    day.run_until("10:05")
    # the reminder rang; its follow-up is waiting, keyed by the reminder's id
    follow_up = next(j for j in day.reminders.scheduler.jobs() if "reminder_id" in j.payload)
    reminder_id = follow_up.payload["reminder_id"]
    assert day.reminders.ack(reminder_id)
    day.run_until("23:59")
    assert day.at("drink water") == ["10:00"]
    assert day.at("Still pending: drink water") == []
    assert "skipped: drink water" not in day.note("2026-12-04")


def test_laptop_asleep_all_day_catches_up_once(day) -> None:
    remind(day, "pay fees", "12:00")
    day.jump_to("23:00")  # brief, reminder and review were all missed
    assert day.at("Good morning") == ["23:00"]
    assert day.at("pay fees") == ["23:00"]
    assert len([t for t, _, text in day.sent if "nightly review" in text]) == 1
    day.run_until("23:59")
    assert len(day.at("Good morning")) == 1  # not again tonight
    assert day.at("Still pending: pay fees") == ["23:15"]


def test_restarting_the_core_schedules_nothing_twice(day) -> None:
    for _ in range(3):  # login, crash-restart, restart from the tray
        day.reminders = day.start()
    kinds = sorted(j.kind for j in day.reminders.scheduler.jobs())
    assert kinds == ["morning_brief", "nightly_review", "vault_backup"]
    day.run_until("08:00")
    assert day.at("Good morning") == ["07:30"]


def test_server_clock_leaves_brief_and_review_to_the_server(day) -> None:
    day.reminders = day.start(clock="server")
    remind(day, "gym bag", "16:30")
    day.run_until("06:00", next_day=True)
    assert day.at("Good morning") == []
    assert not [text for _, _, text in day.sent if "nightly review" in text]
    assert day.at("gym bag") == ["16:30"]  # this laptop's own reminders still ring
    assert list((day.config.data_dir / "backups").glob("*.zip"))  # and it still backs up


def test_job_kinds_have_handlers(day) -> None:
    """Every job in the schedule has something to run it (else it would sit forever)."""
    scheduler: Scheduler = day.reminders.scheduler
    remind(day, "x", "09:00")
    assert {j.kind for j in scheduler.jobs()} <= set(scheduler.handlers)
