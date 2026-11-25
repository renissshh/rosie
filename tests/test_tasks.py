from datetime import date

import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.tasks import TASKS_FILE, Task, TaskError, TaskStore, parse_due, parse_line
from rosie.tools import ToolError
from rosie.vault_writer import VaultWriter

TODAY = date(2026, 11, 26)  # a Thursday


@pytest.fixture
def store(tmp_path):
    return TaskStore(VaultWriter(tmp_path / "rosie-vault"), today=lambda: TODAY)


def text(store):
    return (store.writer.root / TASKS_FILE).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("today", date(2026, 11, 26)),
        ("Tomorrow", date(2026, 11, 27)),
        ("friday", date(2026, 11, 27)),
        ("thursday", date(2026, 12, 3)),  # today is Thursday -> next week's
        ("next monday", date(2026, 11, 30)),
        ("in 3 days", date(2026, 11, 29)),
        ("next week", date(2026, 12, 3)),
        ("2026-12-12", date(2026, 12, 12)),
    ],
)
def test_parse_due(raw, expected):
    assert parse_due(raw, TODAY) == expected


def test_parse_due_rejects_nonsense():
    with pytest.raises(TaskError, match="YYYY-MM-DD"):
        parse_due("someday", TODAY)


def test_line_round_trip_in_obsidian_tasks_format():
    task = Task("a1b2c3", "Revise DBMS", date(2026, 12, 12), "high")
    assert task.line() == "- [ ] Revise DBMS ⏫ 📅 2026-12-12 ^a1b2c3"
    assert parse_line(task.line()) == task
    done = Task("0c4d5e", "Pay fee", None, None, True, date(2026, 11, 19))
    assert parse_line(done.line()) == done


def test_hand_written_lines_count():
    hand = parse_line("- [x] Buy notebook")
    assert hand.done and hand.done_on is None and len(hand.id) == 6
    assert parse_line("Just prose") is None
    assert parse_line("- [ ] Gym 🔽 📅 2026-11-28").priority == "low"


def test_add_and_list_most_urgent_first(store):
    store.add("No date task")
    store.add("Later", due="2026-12-20", priority="high")
    store.add("Soon low", due="tomorrow", priority="low")
    store.add("Soon high", due="tomorrow", priority="high")
    titles = [t.title for t in store.open_tasks()]
    assert titles == ["Soon high", "Soon low", "Later", "No date task"]
    assert text(store).startswith("# tasks\n\n- [ ] No date task ^")


def test_complete(store):
    task = store.add("Submit assignment", due="2026-11-25")
    assert store.overdue() == [task]
    done = store.complete(task.id)
    assert done.done and done.done_on == TODAY
    assert store.complete(task.id) == done  # idempotent
    assert store.open_tasks() == [] and store.overdue() == []
    assert "✅ 2026-11-26" in text(store)


def test_complete_keeps_other_lines(store):
    path = store.writer.root / TASKS_FILE
    path.parent.mkdir(parents=True)
    path.write_text("# tasks\nMy own note.\n- [ ] Gym\n", encoding="utf-8")
    store.complete(store.all()[0].id)
    assert text(store).startswith("# tasks\nMy own note.\n- [x] Gym ✅ 2026-11-26 ^")


@pytest.mark.parametrize(
    "kwargs, match",
    [({"title": "  "}, "title"), ({"title": "x", "priority": "urgent"}, "priority")],
)
def test_add_validation(store, kwargs, match):
    with pytest.raises(TaskError, match=match):
        store.add(**kwargs)


def test_unknown_id(store):
    with pytest.raises(TaskError, match="no task"):
        store.complete("ffffff")


def test_tools_end_to_end_and_allowed(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path))
    out = reg.call("add_task", {"title": "Revise DBMS", "due": "2026-01-01", "priority": "high"})
    assert "OVERDUE" in out
    task_id = out[1:7]
    assert "Revise DBMS" in reg.call("list_tasks", {})
    assert "Revise DBMS" in reg.call("list_tasks", {"status": "overdue"})
    assert "done" in reg.call("complete_task", {"id": task_id})
    assert reg.call("list_tasks", {}) == "no open tasks"
    assert "Revise DBMS" in reg.call("list_tasks", {"status": "done"})
    with pytest.raises(ToolError, match="can't read due date"):
        reg.call("add_task", {"title": "x", "due": "someday"})

    gate = SafetyGate(PermissionPolicy.load())
    for name in ("add_task", "list_tasks", "complete_task"):
        assert gate.decision_for(reg.get(name)) == "allow", name
