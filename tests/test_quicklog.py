import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from rosie.config import Countdown, RosieConfig
from rosie.day import watch_forever
from rosie.quicklog import (
    DeckFeed,
    LogError,
    QuickLog,
    brief_event,
    next_countdown,
    split_duration,
    study_streak,
)
from rosie.tasks import TaskStore
from rosie.vault_writer import VaultWriter

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 26, 19, 40, tzinfo=IST)


@pytest.fixture
def quicklog(tmp_path):
    writer = VaultWriter(tmp_path)
    clock = {"now": NOW}
    tasks = TaskStore(writer, today=lambda: clock["now"].date())
    log = QuickLog(writer, tasks, lambda: clock["now"])
    log.clock = clock  # tests move time by changing clock["now"]
    return log


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("DBMS normal forms 45m", ("DBMS normal forms", 45)),
        ("DBMS 1h 30m", ("DBMS", 90)),
        ("OS 2 hours", ("OS", 120)),
        ("chapter 3, 20 min", ("chapter 3", 20)),
        ("read 30 pages", ("read 30 pages", None)),
        ("45m", ("45m", None)),  # a duration alone isn't a subject
    ],
)
def test_split_duration(text, expected):
    assert split_duration(text) == expected


def test_study_goes_to_todays_study_note(quicklog, tmp_path):
    assert (
        quicklog.log("study", "  DBMS   normal forms 45m ")
        == "Logged study: DBMS normal forms, 45 min"
    )
    quicklog.log("study", "SQL joins")
    note = (tmp_path / "study-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert note == (
        "# Study, Thu 26 Nov 2026\n\n- 19:40 DBMS normal forms (45 min)\n- 19:40 SQL joins\n"
    )


def test_gym_goes_to_the_training_log(quicklog, tmp_path):
    quicklog.log("gym", "bench 3x8 40kg")
    note = (tmp_path / "training-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert note.endswith("- 19:40 Bench press 3x8 @ 40 kg\n")  # the coach's format


def test_task_becomes_a_real_task(quicklog):
    assert quicklog.log("task", "buy notebook") == "Added task: buy notebook"
    assert [t.title for t in quicklog.tasks.open_tasks()] == ["buy notebook"]


def test_log_rejects_empty_and_unknown(quicklog):
    with pytest.raises(LogError, match="type what"):
        quicklog.log("study", "   ")
    with pytest.raises(LogError, match="study, gym or task"):
        quicklog.log("sleep", "8 hours")


def test_log_text_is_capped(quicklog, tmp_path):
    quicklog.log("gym", "x" * 1000)
    note = (tmp_path / "training-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert len(note.splitlines()[-1]) < 320


def test_streak_counts_days_in_a_row(quicklog, tmp_path):
    for day in (23, 24, 25):
        quicklog.clock["now"] = NOW.replace(day=day)
        quicklog.log("study", "DBMS")
    today = date(2026, 11, 26)
    assert study_streak(tmp_path, today) == 3  # today not logged yet: still standing
    quicklog.clock["now"] = NOW
    quicklog.log("study", "SQL")
    assert study_streak(tmp_path, today) == 4
    assert study_streak(tmp_path, date(2026, 11, 28)) == 0  # missed the 27th


def test_streak_ignores_empty_notes(tmp_path):
    (tmp_path / "study-log").mkdir()
    (tmp_path / "study-log" / "2026-11-26.md").write_text("# Study\n", encoding="utf-8")
    assert study_streak(tmp_path, date(2026, 11, 26)) == 0


def test_next_countdown_is_the_nearest_ahead():
    countdowns = [
        Countdown(label="Old exam", date=date(2026, 11, 1)),
        Countdown(label="Viva", date=date(2027, 1, 10)),
        Countdown(label="Exams", date=date(2026, 12, 7)),
    ]
    assert next_countdown(countdowns, date(2026, 11, 26)) == {
        "label": "Exams",
        "date": "2026-12-07",
        "days": 11,
    }
    assert next_countdown([], date(2026, 11, 26)) is None


def test_countdowns_load_from_config():
    config = RosieConfig.model_validate({"countdowns": [{"label": "Exams", "date": "2026-12-07"}]})
    assert config.countdowns[0].date == date(2026, 12, 7)


def test_brief_event_cards(quicklog, tmp_path):
    quicklog.tasks.add("Submit assignment", due="2026-11-25", priority="high")
    quicklog.tasks.add("Revise DBMS", due="2026-11-27")
    quicklog.tasks.add("Clean desk")
    quicklog.tasks.add("Fourth thing")
    event = brief_event(quicklog.tasks, tmp_path, [Countdown(label="Exams", date="2026-12-07")])
    assert event["type"] == "brief"
    assert [t["title"] for t in event["top3"]] == ["Submit assignment", "Revise DBMS", "Clean desk"]
    assert event["top3"][0]["overdue"] is True and event["top3"][0]["priority"] == "high"
    assert event["overdue"] == 1
    assert event["streak"] == 0
    assert event["countdown"]["days"] == 11


class FakeBridge:
    def __init__(self):
        self.handlers, self.sent = {}, []

    def on(self, kind, handler):
        self.handlers[kind] = handler

    def emit(self, event, keep=False):
        self.sent.append(event)


def test_deck_feed_logs_and_refreshes_cards_only_on_change(quicklog):
    bridge = FakeBridge()
    feed = DeckFeed(bridge, quicklog, [])
    feed.refresh()
    feed.refresh()
    assert len(bridge.sent) == 1  # unchanged: sent once
    reply = bridge.handlers["log"]({"type": "log", "what": "task", "text": "buy notebook"})
    assert reply == {"type": "logged", "text": "Added task: buy notebook"}
    assert bridge.sent[-1]["top3"][0]["title"] == "buy notebook"


def test_deck_feed_done_ticks_a_task(quicklog):
    bridge = FakeBridge()
    DeckFeed(bridge, quicklog, [])
    task = quicklog.tasks.add("buy notebook")
    assert bridge.handlers["done"]({"id": task.id})["text"] == "Done: buy notebook"
    assert quicklog.tasks.open_tasks() == []
    assert bridge.sent[-1]["top3"] == []


def test_deck_feed_errors_become_bridge_errors(quicklog):
    from rosie.bridge import BridgeError

    bridge = FakeBridge()
    DeckFeed(bridge, quicklog, [])
    with pytest.raises(BridgeError, match="type what"):
        bridge.handlers["log"]({"what": "study", "text": ""})
    with pytest.raises(BridgeError):
        bridge.handlers["done"]({"id": "nope"})


def test_watch_forever_ticks_until_stopped():
    stop, seen = threading.Event(), []

    def tick(moment):
        seen.append(moment)
        if len(seen) == 3:
            stop.set()

    watch_forever([tick], lambda: NOW, stop, every_s=0)
    assert seen == [NOW, NOW, NOW]
