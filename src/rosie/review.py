"""Nightly review: three questions, answers saved to today's daily note.

    1. What did you get done today?
    2. What got in the way?
    3. What are tomorrow's top 3?

The answers go into rosie-vault/daily/<today>.md together with the tasks that were
actually completed today. The third answer becomes a draft plan: each item is added
as a task due tomorrow (unless it's already on the list) and listed under
"## Draft plan" in tomorrow's note, which the morning brief then picks up.

`NightlyReview` is a small state machine (start -> answer -> answer -> answer), so the
same code drives the terminal (`rosie review`) and Telegram (one message per answer).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta

from rosie.tasks import TaskStore
from rosie.vault_writer import VaultWriter

QUESTIONS = (
    "What did you get done today?",
    "What got in the way?",
    "What are tomorrow's top 3?",
)
REVIEW_JOB = "nightly_review"
_SPLIT = re.compile(r"\s*(?:\n|;|,|\b\d+[.)]\s*)\s*")


def split_items(text: str, limit: int = 3) -> list[str]:
    """'1. DBMS 2. gym, laundry' -> ['DBMS', 'gym', 'laundry']."""
    items = [i.strip(" -*.") for i in _SPLIT.split(text)]
    return [i for i in items if i][:limit]


class NightlyReview:
    def __init__(self, tasks: TaskStore, writer: VaultWriter) -> None:
        self.tasks = tasks
        self.writer = writer
        self.answers: list[str] | None = None  # None = no review running

    @property
    def active(self) -> bool:
        return self.answers is not None

    def start(self) -> str:
        self.answers = []
        return f"Nightly review, 3 quick questions. {QUESTIONS[0]}"

    def answer(self, text: str) -> str:
        """Record an answer; returns the next question or the closing message."""
        if self.answers is None:
            return self.start()
        self.answers.append(text.strip() or "(skipped)")
        if len(self.answers) < len(QUESTIONS):
            return QUESTIONS[len(self.answers)]
        drafted = self._save(self.answers)
        self.answers = None
        plan = f" Tomorrow's draft: {', '.join(drafted)}." if drafted else ""
        return f"Saved to today's note.{plan} Sleep well, VinsmokE."

    def _save(self, answers: list[str]) -> list[str]:
        today = self.tasks.today()
        tomorrow = today + timedelta(days=1)
        done_today = [t.title for t in self.tasks.all() if t.done_on == today]
        lines = ["", "## Nightly review"]
        for question, reply in zip(QUESTIONS, answers, strict=True):
            lines += [f"**{question}**", reply, ""]
        if done_today:
            lines += ["Completed tasks: " + ", ".join(done_today), ""]
        self.writer.append(f"daily/{today:%Y-%m-%d}.md", "\n".join(lines))

        existing = {t.title.lower() for t in self.tasks.open_tasks()}
        drafted = split_items(answers[2]) if answers[2] != "(skipped)" else []
        for item in drafted:
            if item.lower() not in existing:
                self.tasks.add(item, due=tomorrow.isoformat())
        if drafted:
            draft = ["## Draft plan (from last night)"] + [f"- {i}" for i in drafted] + [""]
            self.writer.append(f"daily/{tomorrow:%Y-%m-%d}.md", "\n".join(draft))
        return drafted


def run_in_terminal(review: NightlyReview, read: Callable[[str], str], write) -> None:
    """`rosie review`: ask the three questions in the terminal."""
    write(f"Rosie: {review.start()}")
    while review.active:
        try:
            text = read("You: ")
        except (EOFError, KeyboardInterrupt):
            write("\nRosie: Review stopped, nothing saved.")
            review.answers = None
            return
        write(f"Rosie: {review.answer(text)}")
