from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.quicklog import QuickLog
from rosie.tasks import TaskStore
from rosie.tools import ToolError
from rosie.training import (
    Session,
    SetEntry,
    TrainingLog,
    advice,
    next_weight,
    parse_sets,
    read_history,
    report,
    stall_alerts,
    stalled,
)
from rosie.vault_writer import VaultWriter

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 26, 18, 10, tzinfo=IST)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bench 3x8 at 40 kg", SetEntry("bench press", 3, 8, 40.0)),
        ("squat five by five 60 kilos", SetEntry("squat", 5, 5, 60.0)),
        ("pull ups 3 sets of 10", SetEntry("pull ups", 3, 10, None)),
        ("log bench press 40kg 3x8", SetEntry("bench press", 3, 8, 40.0)),
        ("OHP 3x5 @ 27.5", SetEntry("overhead press", 3, 5, 27.5)),
        ("bench three by eight at forty two", SetEntry("bench press", 3, 8, 42.0)),
        ("deadlift 1x5 at one hundred twenty", SetEntry("deadlift", 1, 5, 120.0)),
        ("Bench 3×8 @40kg", SetEntry("bench press", 3, 8, 40.0)),
    ],
)
def test_parse_sets_typed_and_spoken(text, expected):
    assert parse_sets(text) == expected


@pytest.mark.parametrize("text", ["leg day was fun", "3x8", "bench at 40 kg"])
def test_parse_sets_needs_an_exercise_and_sets_x_reps(text):
    assert parse_sets(text) is None


def test_line_format():
    assert SetEntry("bench press", 3, 8, 40.0).line(NOW) == "- 18:10 Bench press 3x8 @ 40 kg"
    assert SetEntry("pull ups", 3, 10).line(NOW) == "- 18:10 Pull ups 3x10"


def day(n, weight, sets=3, reps=8, exercise="bench press"):
    return Session(date(2026, 11, 1) + timedelta(days=n), SetEntry(exercise, sets, reps, weight))


def test_progression_after_two_matching_sessions():
    assert next_weight([day(0, 40)]) is None
    assert next_weight([day(0, 40), day(3, 40)]) == 42.5
    assert next_weight([day(0, 40, reps=6), day(3, 40)]) is None  # reps went up: keep going
    squat = [day(0, 60, exercise="squat"), day(3, 60, exercise="squat")]
    assert next_weight(squat) == 65.0  # lower body jumps by 5
    assert next_weight([day(0, None), day(3, None)]) is None  # bodyweight


def test_stall_needs_three_flat_sessions_over_two_weeks():
    assert stalled([day(0, 40), day(7, 40), day(14, 40)])
    assert stalled([day(0, 40), day(7, 37.5), day(14, 40)])
    assert not stalled([day(0, 40), day(3, 40), day(6, 40)])  # too soon to call it
    assert not stalled([day(0, 40), day(7, 42.5), day(14, 42.5)])  # it went up
    assert not stalled([day(0, 40), day(14, 40)])  # only two sessions


def write(vault, n, *lines):
    d = date(2026, 11, 26) - timedelta(days=n)
    note = vault / "training-log" / f"{d:%Y-%m-%d}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Training\n\n" + "".join(f"{line}\n" for line in lines), encoding="utf-8")


def test_history_reads_coach_lines_and_skips_free_text(tmp_path):
    write(
        tmp_path,
        1,
        "- 18:00 Bench press 3x8 @ 40 kg",
        "- 18:30 felt strong",
        "- 18:40 Pull ups 3x10",
    )
    history = read_history(tmp_path, date(2026, 11, 26))
    assert [s.entry for s in history] == [
        SetEntry("bench press", 3, 8, 40.0),
        SetEntry("pull ups", 3, 10, None),
    ]


def test_report_and_stall_alerts(tmp_path):
    for n in (20, 13, 6):
        write(tmp_path, n, "- 18:00 Bench press 3x8 @ 40 kg", "- 18:30 Squat 5x5 @ 60 kg")
    write(tmp_path, 2, "- 18:30 Squat 5x5 @ 65 kg")
    text = report(tmp_path, date(2026, 11, 26))
    assert "- Bench press: 3 sessions, last 3x8 @ 40 kg. Bench press has been stuck" in text
    assert "deload to 35 kg" in text
    assert "- Squat: 4 sessions, last 5x5 @ 65 kg" in text
    assert stall_alerts(tmp_path, date(2026, 11, 26)) == [
        advice(read_history(tmp_path, date(2026, 11, 26)), "bench press")
    ]
    assert report(tmp_path / "none", date(2026, 11, 26)).startswith("No training")


def test_log_writes_and_coaches(tmp_path):
    write(tmp_path, 3, "- 18:00 Bench press 3x8 @ 40 kg")
    log = TrainingLog(VaultWriter(tmp_path), lambda: NOW)
    reply = log.log("bench 3x8 at 40kg")
    assert reply == (
        "Logged Bench press 3x8 @ 40 kg. "
        "Bench press: same weight twice in a row, try 42.5 kg next time."
    )
    note = (tmp_path / "training-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert note == "# Training, Thu 26 Nov 2026\n\n- 18:10 Bench press 3x8 @ 40 kg\n"


def test_log_explains_the_format(tmp_path):
    with pytest.raises(ToolError, match="3x8 at 40 kg"):
        TrainingLog(VaultWriter(tmp_path), lambda: NOW).log("did some cardio")


def test_deck_gym_button_uses_the_coach_format(tmp_path):
    writer = VaultWriter(tmp_path)
    quick = QuickLog(writer, TaskStore(writer, today=NOW.date), lambda: NOW)
    assert quick.log("gym", "bench 3x8 40kg") == "Logged training: Bench press 3x8 @ 40 kg"
    assert quick.log("gym", "30 min cardio") == "Logged training: 30 min cardio"
    note = (tmp_path / "training-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert "- 18:10 Bench press 3x8 @ 40 kg\n- 18:10 30 min cardio\n" in note


def test_tools_use_the_training_permission(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path))
    assert reg.get("log_sets").action == "log.training"
    assert reg.get("training_report").tier == "read"
