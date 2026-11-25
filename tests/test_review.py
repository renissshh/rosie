from datetime import date

import pytest

from rosie.__main__ import start_reminders, telegram_reply
from rosie.config import RosieConfig
from rosie.review import QUESTIONS, REVIEW_JOB, NightlyReview, run_in_terminal, split_items
from rosie.tasks import TaskStore
from rosie.vault_writer import VaultWriter

TODAY = date(2026, 11, 26)


@pytest.fixture
def review(tmp_path):
    writer = VaultWriter(tmp_path / "rosie-vault")
    return NightlyReview(TaskStore(writer, today=lambda: TODAY), writer)


def note(review, day):
    return (review.writer.root / "daily" / f"{day}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text, items",
    [
        ("1. DBMS 2. gym 3. laundry", ["DBMS", "gym", "laundry"]),
        ("DBMS, gym; laundry, extra", ["DBMS", "gym", "laundry"]),
        ("- DBMS\n- gym", ["DBMS", "gym"]),
        ("", []),
    ],
)
def test_split_items(text, items):
    assert split_items(text) == items


def test_three_questions_then_saved(review):
    done = review.tasks.add("Submit assignment")
    review.tasks.complete(done.id)
    review.tasks.add("gym", due="tomorrow")  # already planned: not added twice

    assert review.start().endswith(QUESTIONS[0])
    assert review.answer("Finished the assignment") == QUESTIONS[1]
    assert review.answer("Phone, mostly") == QUESTIONS[2]
    closing = review.answer("1. DBMS normal forms 2. gym 3. call mom")
    assert "DBMS normal forms, gym, call mom" in closing
    assert not review.active

    today = note(review, "2026-11-26")
    assert "## Nightly review" in today
    assert "**What got in the way?**\nPhone, mostly" in today
    assert "Completed tasks: Submit assignment" in today

    tomorrow = note(review, "2026-11-27")
    assert tomorrow.startswith("## Draft plan (from last night)\n- DBMS normal forms")
    titles = [t.title for t in review.tasks.open_tasks()]
    assert sorted(titles) == ["DBMS normal forms", "call mom", "gym"]
    assert all(t.due == date(2026, 11, 27) for t in review.tasks.open_tasks())


def test_skipped_answers(review):
    review.start()
    for _ in QUESTIONS:
        closing = review.answer("  ")
    assert "draft" not in closing
    assert "(skipped)" in note(review, "2026-11-26")
    assert review.tasks.open_tasks() == []


def test_answer_without_start_starts(review):
    assert review.answer("hi").endswith(QUESTIONS[0])
    assert review.active


def test_terminal_flow_and_interrupt(review):
    out = []
    replies = iter(["did DBMS", "nothing", "gym"])
    run_in_terminal(review, lambda prompt: next(replies), out.append)
    assert out[-1].startswith("Rosie: Saved")

    def interrupted(prompt):
        raise KeyboardInterrupt

    out.clear()
    run_in_terminal(review, interrupted, out.append)
    assert "nothing saved" in out[-1] and not review.active


def test_telegram_routes_answers_to_the_review(review):
    class Session:
        def ask(self, text):
            return type("R", (), {"text": f"chat: {text}"})()

    session = Session()
    assert telegram_reply("hi", review, session) == "chat: hi"
    assert telegram_reply("/review", review, session).endswith(QUESTIONS[0])
    assert telegram_reply("did DBMS", review, session) == QUESTIONS[1]
    telegram_reply("phone", review, session)
    assert telegram_reply("gym", review, session).startswith("Saved")
    assert telegram_reply("hi again", review, session) == "chat: hi again"


def test_review_is_scheduled_daily_and_can_start_remotely(tmp_path):
    started = []
    config = RosieConfig(data_dir=tmp_path, review_time="22:15")
    reminders, stop = start_reminders(
        config, lambda t, x: None, on_review=lambda: started.append(1)
    )
    stop.set()
    sched = reminders.scheduler
    assert [j.rule for j in sched.jobs() if j.kind == REVIEW_JOB] == ["daily@22:15"]
    sched.handlers[REVIEW_JOB](None)
    assert started == [1]


def test_review_without_remote_just_nudges(tmp_path):
    sent = []
    reminders, stop = start_reminders(RosieConfig(data_dir=tmp_path), lambda t, x: sent.append(x))
    stop.set()
    reminders.scheduler.handlers[REVIEW_JOB](None)
    assert "rosie review" in sent[-1]
