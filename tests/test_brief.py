from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from rosie.__main__ import main, start_reminders
from rosie.brief import BRIEF_JOB, MorningBrief, avoided_task, build_brief, short_brief
from rosie.config import RosieConfig
from rosie.reminders import Reminders
from rosie.scheduler import Scheduler
from rosie.tasks import Task, TaskStore
from rosie.vault_writer import VaultWriter

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 11, 26)  # Thursday


@pytest.fixture
def env(tmp_path):
    clock = {"t": datetime(2026, 11, 26, 7, 30, tzinfo=IST)}
    writer = VaultWriter(tmp_path / "rosie-vault")
    tasks = TaskStore(writer, today=lambda: clock["t"].date())
    sched = Scheduler(tmp_path / "s.db", now=lambda: clock["t"].astimezone(UTC))
    sent = []
    reminders = Reminders(sched, lambda title, text: sent.append((title, text)), writer)
    return tasks, reminders, writer, sent, clock


def add_old(tasks, title, days_ago, **kw):
    """Add a task as if it was created some days ago."""
    task = tasks.add(title, **kw)
    path = tasks.writer.root / "tasks" / "tasks.md"
    text = path.read_text(encoding="utf-8")
    old = (TODAY - timedelta(days=days_ago)).isoformat()
    path.write_text(
        text.replace(f"➕ {TODAY.isoformat()} ^{task.id}", f"➕ {old} ^{task.id}"), encoding="utf-8"
    )
    return task


def test_full_brief(env):
    tasks, reminders, *_ = env
    tasks.add("Revise DBMS", due="tomorrow", priority="high")
    tasks.add("Submit assignment", due="2026-11-25")
    tasks.add("Buy notebook")
    add_old(tasks, "Clean desk", 9)
    reminders.remind("gym", datetime(2026, 11, 26, 18, tzinfo=IST))
    reminders.remind("not today", datetime(2026, 11, 27, 9, tzinfo=IST))

    text = build_brief(tasks, reminders)
    assert text.startswith("# Morning brief, Thu 26 Nov\n\n## Top 3\n")
    assert "1. Submit assignment, due Wed 25 Nov" in text
    assert "2. Revise DBMS (high), due Fri 27 Nov" in text
    assert "## Today\n- 18:00 gym\n" in text and "not today" not in text
    assert "## Overdue\n- Submit assignment" in text
    assert '"Clean desk" has been open for 9 days' in text


def test_empty_list(env):
    tasks, *_ = env
    text = build_brief(tasks)
    assert "Nothing on the list" in text
    assert "Overdue" not in text and "Avoiding" not in text
    assert short_brief(tasks) == "Nothing on your list."


def test_avoided_skips_top3_and_new_tasks():
    t = [
        Task("a", "new", created=TODAY),
        Task("b", "old top", created=TODAY - timedelta(days=10)),
        Task("c", "older", created=TODAY - timedelta(days=5)),
        Task("d", "unknown age"),
    ]
    assert avoided_task(t, TODAY, skip={"b"}).id == "c"
    assert avoided_task(t[:1], TODAY, skip=set()) is None


def test_run_writes_daily_note_and_notifies(env):
    tasks, reminders, writer, sent, _ = env
    tasks.add("Submit assignment", due="2026-11-25")
    MorningBrief(tasks, writer, reminders.notify, reminders).run()
    daily = (writer.root / "daily" / "2026-11-26.md").read_text(encoding="utf-8")
    assert daily.startswith("# Morning brief, Thu 26 Nov")
    assert sent == [("Good morning", "Top 3: Submit assignment (1 overdue)")]


def test_schedule_is_idempotent_and_fires(env):
    tasks, reminders, writer, sent, clock = env
    brief = MorningBrief(tasks, writer, reminders.notify, reminders)
    brief.schedule("07:45")
    brief.schedule("07:45")
    jobs = [j for j in reminders.scheduler.jobs() if j.kind == BRIEF_JOB]
    assert len(jobs) == 1 and jobs[0].next_run == datetime(2026, 11, 26, 7, 45, tzinfo=IST)
    brief.schedule("08:00")  # changed time replaces the old job
    assert [j.rule for j in reminders.scheduler.jobs()] == ["daily@08:00"]
    clock["t"] = datetime(2026, 11, 26, 8, 0, tzinfo=IST)
    reminders.scheduler.run_pending()
    assert sent and sent[0][0] == "Good morning"


def test_schedule_needs_scheduler(env):
    tasks, _, writer, *_ = env
    with pytest.raises(ValueError):
        MorningBrief(tasks, writer, print).schedule()


def test_cli_brief_and_chat_schedules_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["brief"]) == 0
    assert "## Top 3" in capsys.readouterr().out

    reminders, stop = start_reminders(RosieConfig(data_dir=tmp_path / "R2"), lambda t, x: None)
    stop.set()
    assert [j.rule for j in reminders.scheduler.jobs() if j.kind == BRIEF_JOB] == ["daily@07:30"]


def test_coach_section_lists_what_the_coaches_found(env):
    tasks, *_ = env
    text = build_brief(tasks, coach=lambda: ["OS: last studied 8 days ago"])
    assert text.endswith("## Coach\n- OS: last studied 8 days ago\n")
    assert "## Coach" not in build_brief(tasks, coach=lambda: [])


def test_coach_notes_from_the_logs(tmp_path):
    from rosie.brief import coach_notes

    def log(folder, days_ago, line):
        day = TODAY - timedelta(days=days_ago)
        note = tmp_path / folder / f"{day:%Y-%m-%d}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        with note.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    assert coach_notes(tmp_path, ["DBMS", "OS"], TODAY) == []  # nothing logged: quiet
    log("study-log", 1, "- 19:00 DBMS keys (60 min)")
    log("study-log", 9, "- 19:00 OS paging (60 min)")
    for days_ago in (20, 13, 6):
        log("training-log", days_ago, "- 18:00 Bench press 3x8 @ 40 kg")
    notes = coach_notes(tmp_path, ["DBMS", "OS"], TODAY)
    assert notes[0] == "OS: last studied 9 days ago"
    assert notes[1].startswith("Bench press has been stuck at 40 kg")
