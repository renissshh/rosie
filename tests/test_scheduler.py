import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rosie.scheduler import ScheduleError, Scheduler, next_after, validate_rule

IST = ZoneInfo("Asia/Kolkata")


def ist(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t.astimezone(UTC)

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock(ist(26, 9))  # Thursday 26 Nov, 09:00 IST


@pytest.fixture
def sched(tmp_path, clock):
    return Scheduler(tmp_path / "scheduler.db", "Asia/Kolkata", now=clock)


@pytest.mark.parametrize(
    "rule", ["once", "daily@07:30", "weekly:mon,wed,fri@18:00", "every:90m", "daily@7:05"]
)
def test_valid_rules(rule):
    validate_rule(rule)


@pytest.mark.parametrize(
    "rule", ["daily@25:00", "daily@07:60", "weekly:funday@10:00", "every:0m", "cron * * *", ""]
)
def test_invalid_rules(rule):
    with pytest.raises(ScheduleError):
        validate_rule(rule)


def test_next_after_in_ist():
    now = ist(26, 9).astimezone(UTC)
    assert next_after("daily@07:30", now, IST) == ist(27, 7, 30)
    assert next_after("daily@21:00", now, IST) == ist(26, 21)
    assert next_after("weekly:mon,fri@18:00", now, IST) == ist(27, 18)
    assert next_after("weekly:thu@09:00", now, IST) == datetime(2026, 12, 3, 9, tzinfo=IST)
    assert next_after("every:90m", now, IST) == ist(26, 10, 30)
    assert next_after("once", now, IST) is None


def test_one_off_runs_once_then_disappears(sched, clock):
    ran = []
    sched.on("reminder", lambda job: ran.append(job.payload["text"]))
    sched.add("reminder", at=ist(26, 9, 30), payload={"text": "drink water"})
    assert sched.run_pending() == []
    clock.advance(minutes=30)
    assert [j.kind for j in sched.run_pending()] == ["reminder"]
    assert ran == ["drink water"]
    assert sched.jobs() == []


def test_jobs_survive_a_restart(tmp_path, clock):
    first = Scheduler(tmp_path / "s.db", now=clock)
    job = first.add("reminder", "daily@21:00", payload={"text": "review"})
    second = Scheduler(tmp_path / "s.db", now=clock)
    assert second.jobs() == [job]


def test_daily_job_moves_to_tomorrow(sched, clock):
    sched.on("brief", lambda job: None)
    job = sched.add("brief", "daily@09:30")
    assert job.next_run == ist(26, 9, 30)
    clock.advance(minutes=31)
    sched.run_pending()
    assert sched.get(job.id).next_run == ist(27, 9, 30)


def test_missed_runs_are_merged_into_one(sched, clock):
    calls = []
    sched.on("brief", calls.append)
    job = sched.add("brief", "daily@09:30")
    clock.advance(days=3)  # laptop was off for three mornings
    sched.run_pending()
    assert len(calls) == 1
    assert sched.get(job.id).next_run == ist(29, 9, 30)  # next future morning


def test_crashing_handler_does_not_block_others(sched, clock):
    seen = []

    def boom(job):
        raise RuntimeError("bug")

    sched.on("bad", boom)
    sched.on("good", lambda job: seen.append(job.id))
    sched.add("bad", at=ist(26, 9))
    good = sched.add("good", at=ist(26, 9))
    assert len(sched.run_pending()) == 2
    assert seen == [good.id]
    assert sched.jobs() == []


def test_unknown_kind_is_left_for_later(sched):
    sched.add("mystery", at=ist(26, 8))
    assert sched.run_pending() == []
    assert len(sched.jobs()) == 1


def test_handler_can_reschedule_its_own_job(sched, clock):
    def snooze(job):
        sched.reschedule(job.id, clock() + timedelta(minutes=10))

    sched.on("reminder", snooze)
    job = sched.add("reminder", at=ist(26, 9))
    sched.run_pending()
    assert sched.get(job.id).next_run == ist(26, 9, 10)


def test_add_validation(sched):
    with pytest.raises(ScheduleError, match="needs a time"):
        sched.add("reminder")
    with pytest.raises(ScheduleError, match="timezone-aware"):
        sched.add("reminder", at=datetime(2026, 11, 26, 9))
    assert sched.cancel("nope") is False


def test_run_forever_stops(sched):
    fired = threading.Event()
    sched.on("tick", lambda job: fired.set())
    sched.add("tick", at=ist(26, 9))
    stop = threading.Event()
    thread = threading.Thread(target=sched.run_forever, args=(stop, 0.01))
    thread.start()
    assert fired.wait(timeout=2)
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
