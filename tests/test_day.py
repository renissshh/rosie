from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from rosie.config import DayBlock, RosieConfig
from rosie.day import DayWatcher, blocks_for, day_event, focus_block, marks_for
from rosie.scheduler import Job

IST = ZoneInfo("Asia/Kolkata")
THU = datetime(2026, 11, 26, 20, 0, tzinfo=IST)  # a Thursday evening

BLOCKS = [
    DayBlock(start="19:00", end="21:00", kind="study", label="DBMS"),
    DayBlock(start="9:00", end="15:30", kind="college", days=["mon", "tue", "wed", "thu", "fri"]),
    DayBlock(start="10:00", end="12:00", kind="study", label="Weekend revision", days=["Sat"]),
    DayBlock(start="23:30", end="06:30", kind="sleep"),
]


def job(kind, local, text=None, id="j1"):
    payload = {"text": text} if text else {}
    return Job(id, kind, "once", local.astimezone(UTC), payload)


def test_block_times_are_normalised_and_checked():
    assert DayBlock(start="9:05", end="10:00").start == "09:05"
    for bad in ["25:00", "9", "9:5", "nine"]:
        with pytest.raises(ValidationError):
            DayBlock(start=bad, end="10:00")
    with pytest.raises(ValidationError, match="unknown day"):
        DayBlock(start="09:00", end="10:00", days=["funday"])


def test_config_has_no_blocks_by_default():
    assert RosieConfig().day_blocks == []


def test_blocks_for_picks_todays_weekday_in_time_order():
    thursday = [b.kind for b in blocks_for(BLOCKS, THU.date())]
    assert thursday == ["college", "study", "sleep"]
    saturday = datetime(2026, 11, 28, tzinfo=IST).date()
    assert [b.label for b in blocks_for(BLOCKS, saturday)] == ["Weekend revision", "DBMS", ""]


def test_marks_are_todays_reminders_brief_and_review():
    jobs = [
        job("reminder", THU.replace(hour=21, minute=30), "call mom"),
        job("morning_brief", THU.replace(day=27, hour=7, minute=30)),  # tomorrow: not shown
        job("nightly_review", THU.replace(hour=22)),
        job("reminder_followup", THU.replace(hour=20, minute=15), "x"),  # internal: not shown
    ]
    assert marks_for(jobs, THU.date(), IST) == [
        {"at": "21:30", "kind": "reminder", "text": "call mom"},
        {"at": "22:00", "kind": "review", "text": "Nightly review"},
    ]


def test_day_event_shape():
    event = day_event(BLOCKS, [], THU)
    assert event["type"] == "day" and event["date"] == "2026-11-26"
    assert event["blocks"][0] == {
        "start": "09:00",
        "end": "15:30",
        "kind": "college",
        "label": "College",
    }
    assert event["marks"] == []


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(18, 59, None), (19, 0, "DBMS"), (20, 59, "DBMS"), (21, 0, None)],
)
def test_focus_during_study_blocks_only(hour, minute, expected):
    block = focus_block(BLOCKS, THU.replace(hour=hour, minute=minute))
    assert (block.label if block else None) == expected


def test_focus_block_crossing_midnight_belongs_to_the_day_it_started():
    late = [DayBlock(start="22:00", end="01:00", kind="study", label="Night owl", days=["thu"])]
    assert focus_block(late, THU.replace(hour=23)).label == "Night owl"
    friday_0030 = datetime(2026, 11, 27, 0, 30, tzinfo=IST)
    assert focus_block(late, friday_0030).label == "Night owl"
    saturday_0030 = datetime(2026, 11, 28, 0, 30, tzinfo=IST)
    assert focus_block(late, saturday_0030) is None  # Friday has no such block


def test_watcher_sends_only_changes():
    sent = []
    jobs = []
    watcher = DayWatcher(BLOCKS, lambda: jobs, lambda event, keep: sent.append((event, keep)))
    first = watcher.tick(THU.replace(hour=18))
    assert [e["type"] for e in first] == ["day"]  # not studying: focus stays off, unsent
    assert watcher.tick(THU.replace(hour=18, minute=30)) == []
    jobs.append(job("reminder", THU.replace(hour=21), "stretch"))
    assert [e["type"] for e in watcher.tick(THU.replace(hour=18, minute=31))] == ["day"]
    assert all(keep for _, keep in sent)


def test_watcher_turns_focus_on_and_off():
    watcher = DayWatcher(BLOCKS, list, lambda event, keep: None)
    watcher.tick(THU.replace(hour=18))
    on = watcher.tick(THU.replace(hour=19))
    assert on == [{"type": "focus", "on": True, "label": "DBMS"}]
    assert watcher.tick(THU.replace(hour=20)) == []
    assert watcher.tick(THU.replace(hour=21)) == [{"type": "focus", "on": False, "label": ""}]


def test_watcher_sends_a_new_day_after_midnight():
    watcher = DayWatcher(BLOCKS, list, lambda event, keep: None)
    watcher.tick(THU.replace(hour=23, minute=59))
    events = watcher.tick(datetime(2026, 11, 27, 0, 0, tzinfo=IST))
    assert events[0]["date"] == "2026-11-27"
