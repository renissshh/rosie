from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rosie.__main__ import build_registry, start_reminders
from rosie.config import RosieConfig
from rosie.reminders import (
    FOLLOW,
    REMINDER,
    ReminderError,
    Reminders,
    parse_when,
    register_reminder_tools,
    repeat_rule,
)
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.scheduler import Scheduler
from rosie.tools import ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 26, 21, 0, tzinfo=IST)  # Thursday 9 PM


def at(hour, minute=0, day=26):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t.astimezone(UTC)

    def advance(self, minutes):
        self.t += timedelta(minutes=minutes)


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    sched = Scheduler(tmp_path / "s.db", now=clock)
    sent = []
    vault = tmp_path / "rosie-vault"
    rem = Reminders(sched, lambda title, text: sent.append(text), VaultWriter(vault))
    return rem, sched, clock, sent, vault


@pytest.mark.parametrize(
    "text, expected",
    [
        ("21:30", at(21, 30)),
        ("20:00", at(20, 0, day=27)),  # already passed today -> tomorrow
        ("tomorrow 7:30", at(7, 30, day=27)),
        ("tomorrow 7am", at(7, 0, day=27)),
        ("9pm", at(21, 0, day=27)),
        ("12am", at(0, 0, day=27)),
        ("at 22", at(22, 0)),
        ("in 20 minutes", at(21, 20)),
        ("in 2 hours", at(23, 0)),
        ("2026-12-12 09:00", datetime(2026, 12, 12, 9, tzinfo=IST)),
    ],
)
def test_parse_when(text, expected):
    assert parse_when(text, NOW) == expected


@pytest.mark.parametrize("text", ["someday", "25:00", "tomorrow at noonish", "2026-13-01 09:00"])
def test_parse_when_rejects(text):
    with pytest.raises(ReminderError):
        parse_when(text, NOW)


def test_repeat_rules():
    assert repeat_rule(None, at(7, 30)) == "once"
    assert repeat_rule("daily", at(7, 30)) == "daily@07:30"
    assert repeat_rule("weekdays", at(7, 30)) == "weekly:mon,tue,wed,thu,fri@07:30"
    assert repeat_rule("Monday, Thursday", at(18)) == "weekly:mon,thu@18:00"
    with pytest.raises(ReminderError):
        repeat_rule("fortnightly", at(7))


def test_fire_then_one_follow_up_then_skip_logged(env):
    rem, sched, clock, sent, vault = env
    rem.remind("revise DBMS", at(21, 30))
    clock.advance(30)
    sched.run_pending()
    assert sent == ["revise DBMS"]
    clock.advance(15)
    sched.run_pending()
    assert sent == ["revise DBMS", "Still pending: revise DBMS"]
    clock.advance(15)
    sched.run_pending()
    assert len(sent) == 2  # no more nagging
    daily = (vault / "daily" / "2026-11-26.md").read_text(encoding="utf-8")
    assert daily == "- 22:00 skipped: revise DBMS\n"
    assert sched.jobs() == []


def test_ack_stops_follow_up(env):
    rem, sched, clock, sent, vault = env
    job = rem.remind("drink water", at(21, 5))
    clock.advance(5)
    sched.run_pending()
    assert [j.kind for j in sched.jobs()] == [FOLLOW]
    assert rem.ack(job.id) is True
    assert rem.ack(job.id) is False
    clock.advance(60)
    sched.run_pending()
    assert sent == ["drink water"]
    assert not (vault / "daily").exists()


def test_snooze(env):
    rem, sched, clock, sent, _ = env
    job = rem.remind("call mom", at(21, 0))
    sched.run_pending()
    snoozed = rem.snooze(job.id, 10)
    assert [j.kind for j in sched.jobs()] == [REMINDER]
    clock.advance(10)
    sched.run_pending()
    assert sent == ["call mom", "call mom"]
    assert snoozed.payload["snoozed"] == job.id
    with pytest.raises(ReminderError):
        rem.snooze("nope")


def test_recurring_keeps_its_schedule(env):
    rem, sched, clock, sent, _ = env
    job = rem.remind("gym", at(21, 10), repeat="daily")
    clock.advance(10)
    sched.run_pending()
    rem.ack(job.id)
    assert [(j.kind, j.next_run) for j in sched.jobs()] == [(REMINDER, at(21, 10, day=27))]


def test_cancel(env):
    rem, sched, *_ = env
    job = rem.remind("x", at(22))
    assert rem.cancel(job.id) is True
    assert sched.jobs() == []


def test_empty_text_rejected(env):
    with pytest.raises(ReminderError):
        env[0].remind("  ", at(22))


def test_tools(env):
    rem, sched, clock, sent, _ = env
    reg = ToolRegistry()
    register_reminder_tools(reg, rem)
    out = reg.call("set_reminder", {"text": "revise DBMS", "when": "21:30", "repeat": "weekdays"})
    assert out.startswith("set [") and "Thu 26 Nov 21:30: revise DBMS (repeats:" in out
    job_id = out[5:13]
    assert job_id in reg.call("list_reminders", {})
    clock.advance(30)
    sched.run_pending()
    assert reg.call("reminder_done", {"id": job_id}) == "done"
    assert "snoozed to" in reg.call("snooze_reminder", {"id": job_id, "minutes": 5})
    with pytest.raises(ToolError, match="can't read"):
        reg.call("set_reminder", {"text": "x", "when": "someday"})
    gate = SafetyGate(PermissionPolicy.load())
    assert all(gate.decision_for(reg.get(n)) == "allow" for n in reg.names())


def test_chat_wiring_registers_reminder_tools(tmp_path):
    config = RosieConfig(data_dir=tmp_path)
    reminders, stop = start_reminders(config, lambda title, text: None)
    try:
        names = build_registry(config, reminders).names()
    finally:
        stop.set()
    assert {"set_reminder", "list_reminders", "snooze_reminder"} <= set(names)
    assert "set_reminder" not in build_registry(config).names()
