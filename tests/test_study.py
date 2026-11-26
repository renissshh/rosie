from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.study import (
    MAX_SESSION_MIN,
    StudyTimer,
    SubjectStats,
    read_sessions,
    report,
    subject_of,
    subject_stats,
    weak_subjects,
)
from rosie.tools import ToolError
from rosie.vault_writer import VaultWriter

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 11, 26)
SUBJECTS = ["DBMS", "OS", "Java", "Data Structures"]


def write_log(vault, day, *lines):
    note = vault / "study-log" / f"{day:%Y-%m-%d}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Study\n\n" + "".join(line + "\n" for line in lines), encoding="utf-8")


def test_read_sessions_parses_timed_and_untimed_lines(tmp_path):
    write_log(tmp_path, TODAY, "- 19:40 DBMS normal forms (45 min)", "- 21:00 OS revision", "notes")
    sessions = read_sessions(tmp_path, TODAY - timedelta(days=3), TODAY)
    assert [(s.time, s.text, s.minutes) for s in sessions] == [
        ("19:40", "DBMS normal forms", 45),
        ("21:00", "OS revision", None),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("DBMS normal forms", "DBMS"),
        ("dbms joins", "DBMS"),
        ("revised data structures: trees", "Data Structures"),
        ("javascript basics", "other"),  # "Java" must be a whole word
        ("Maths integrals", "other"),
    ],
)
def test_subject_of_matches_whole_words(text, expected):
    assert subject_of(text, SUBJECTS) == expected


def test_without_a_subject_list_the_first_word_is_the_subject():
    assert subject_of("DBMS normal forms", []) == "DBMS"


def test_stats_per_subject(tmp_path):
    write_log(tmp_path, TODAY - timedelta(days=2), "- 19:00 DBMS joins (60 min)")
    write_log(tmp_path, TODAY, "- 19:00 DBMS keys (30 min)", "- 20:00 OS paging")
    stats = {
        s.subject: s
        for s in subject_stats(read_sessions(tmp_path, TODAY - timedelta(13), TODAY), SUBJECTS)
    }
    assert stats["DBMS"] == SubjectStats("DBMS", 90, 2, TODAY)
    assert stats["OS"] == SubjectStats("OS", 0, 1, TODAY)
    assert stats["Java"].last is None


def test_weak_subjects_worst_first():
    stats = [
        SubjectStats("DBMS", 300, 6, TODAY),
        SubjectStats("OS", 40, 2, TODAY - timedelta(days=1)),  # far below average
        SubjectStats("Java", 120, 2, TODAY - timedelta(days=9)),  # stale
        SubjectStats("Data Structures", 0, 0, None),  # never
    ]
    weak = weak_subjects(stats, TODAY)
    assert [(s.subject, why) for s, why in weak] == [
        ("Data Structures", "not studied in the last 14 days"),
        ("Java", "last studied 9 days ago"),
        ("OS", "40 min vs 115 min average"),
    ]


def test_report_reads_like_a_summary(tmp_path):
    write_log(tmp_path, TODAY, "- 19:00 DBMS keys (90 min)")
    text = report(tmp_path, ["DBMS", "OS"], TODAY)
    assert "- DBMS: 90 min in 1 sessions, last Thu 26 Nov" in text
    assert "Needs attention:\n- OS: not studied in the last 14 days" in text
    assert report(tmp_path / "empty", [], TODAY).startswith("No study sessions")


@pytest.fixture
def timer(tmp_path):
    clock = {"now": datetime(2026, 11, 26, 19, 0, tzinfo=IST)}
    timer = StudyTimer(
        tmp_path / "state.json", VaultWriter(tmp_path / "vault"), lambda: clock["now"]
    )
    timer.clock = clock
    return timer


def test_timer_logs_the_minutes(timer, tmp_path):
    assert timer.start("DBMS") == "Started DBMS at 19:00. Say when you're done."
    timer.clock["now"] += timedelta(minutes=52, seconds=40)
    assert timer.stop() == "Logged DBMS: 52 min."
    note = (tmp_path / "vault" / "study-log" / "2026-11-26.md").read_text(encoding="utf-8")
    assert note.endswith("- 19:00 DBMS (52 min)\n")
    assert timer.current() is None


def test_timer_survives_a_restart(timer, tmp_path):
    timer.start("OS")
    again = StudyTimer(timer.state_file, timer.writer, timer.now)
    assert again.current()["subject"] == "OS"


def test_one_session_at_a_time_and_stop_needs_a_session(timer):
    with pytest.raises(ToolError, match="no study session"):
        timer.stop()
    timer.start("OS")
    with pytest.raises(ToolError, match="already running"):
        timer.start("DBMS")
    with pytest.raises(ToolError, match="which subject"):
        StudyTimer(timer.state_file.with_name("x.json"), timer.writer, timer.now).start("  ")


def test_a_forgotten_timer_is_capped(timer):
    timer.start("Java")
    timer.clock["now"] += timedelta(hours=30)
    assert f"{MAX_SESSION_MIN} min (capped" in timer.stop()


def test_a_session_past_midnight_is_logged_on_the_day_it_started(timer, tmp_path):
    timer.clock["now"] = datetime(2026, 11, 26, 23, 30, tzinfo=IST)
    timer.start("DBMS")
    timer.clock["now"] += timedelta(hours=1)
    timer.stop()
    assert (tmp_path / "vault" / "study-log" / "2026-11-26.md").is_file()


def test_a_corrupt_state_file_means_no_session(timer):
    timer.state_file.write_text("{not json", encoding="utf-8")
    assert timer.current() is None


def test_tools_are_registered_with_the_study_permission(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path, subjects=["DBMS"]))
    assert reg.get("start_study").action == "log.study"
    assert reg.get("stop_study").action == "log.study"
    assert reg.get("study_report").tier == "read"
    assert "No study sessions" in reg.get("study_report").handler()
