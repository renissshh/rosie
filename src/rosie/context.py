"""Context builder: what Rosie should have in mind before answering.

Before every reply the chat asks `ContextBuilder.build(user_message)` for a short
markdown block that goes into the system prompt:

    ## What you know about VinsmokE
    - [f3a9c1] (study) DBMS exam is on 12 Dec
    ## His tasks
    - [a1b2c3] Submit DBMS assignment due Wed 25 Nov OVERDUE

Facts are the ones whose words match the message (SQLite full-text search), plus
nothing else, so a small local model isn't flooded. Tasks are overdue + due today,
because those matter whatever he asks. Any failure here only drops the context:
Rosie still answers.
"""

from __future__ import annotations

import logging

from rosie.memory import FactStore
from rosie.tasks import TaskStore

log = logging.getLogger("rosie.context")

MAX_FACTS = 5
MAX_TASKS = 5


class ContextBuilder:
    def __init__(self, facts: FactStore | None = None, tasks: TaskStore | None = None) -> None:
        self.facts = facts
        self.tasks = tasks

    def _fact_lines(self, message: str) -> list[str]:
        if self.facts is None:
            return []
        return [f"- [{f.id}] ({f.topic}) {f.text}" for f in self.facts.search(message, MAX_FACTS)]

    def _task_lines(self) -> list[str]:
        if self.tasks is None:
            return []
        today = self.tasks.today()
        urgent = [t for t in self.tasks.open_tasks() if t.due and t.due <= today]
        return [f"- {t.show(today)}" for t in urgent[:MAX_TASKS]]

    def build(self, message: str) -> str:
        sections = []
        try:
            facts = self._fact_lines(message)
            tasks = self._task_lines()
        except Exception as exc:  # context is a bonus; never block a reply on it
            log.warning("context skipped: %s", exc)
            return ""
        if facts:
            sections.append("## What you know about VinsmokE\n" + "\n".join(facts))
        if tasks:
            sections.append("## Due today or overdue\n" + "\n".join(tasks))
        return "\n\n".join(sections)
