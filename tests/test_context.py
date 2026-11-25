from datetime import date, datetime
from zoneinfo import ZoneInfo

from rosie.agent import Agent
from rosie.chat import ChatSession
from rosie.context import MAX_FACTS, ContextBuilder
from rosie.llm import ChatResult
from rosie.memory import FactStore
from rosie.tasks import TaskStore
from rosie.tools import ToolRegistry
from rosie.vault_writer import VaultWriter

TODAY = date(2026, 11, 26)


def stores(tmp_path):
    writer = VaultWriter(tmp_path / "rosie-vault")
    return FactStore(writer, tmp_path / "index" / "m.db"), TaskStore(writer, lambda: TODAY)


def test_relevant_facts_and_urgent_tasks(tmp_path):
    facts, tasks = stores(tmp_path)
    exam = facts.remember("DBMS exam is on 12 Dec", "study")
    facts.remember("Likes masala chai", "food")
    tasks.add("Submit DBMS assignment", due="2026-11-25")
    tasks.add("Gym", due="today")
    tasks.add("Buy notebook", due="2026-12-20")

    text = ContextBuilder(facts, tasks).build("when is my DBMS exam?")
    assert f"- [{exam.id}] (study) DBMS exam is on 12 Dec" in text
    assert "chai" not in text  # not relevant to this message
    assert "Submit DBMS assignment" in text and "OVERDUE" in text
    assert "Gym" in text
    assert "Buy notebook" not in text  # not due yet


def test_nothing_known_gives_empty_context(tmp_path):
    facts, tasks = stores(tmp_path)
    assert ContextBuilder(facts, tasks).build("hello") == ""
    assert ContextBuilder().build("hello") == ""


def test_fact_count_is_capped(tmp_path):
    facts, _ = stores(tmp_path)
    for i in range(MAX_FACTS + 3):
        facts.remember(f"DBMS fact number {i}", "study")
    assert ContextBuilder(facts).build("dbms").count("\n- ") == MAX_FACTS


def test_broken_store_never_blocks_a_reply(tmp_path):
    class Broken:
        def search(self, *a):
            raise OSError("disk gone")

    assert ContextBuilder(Broken()).build("dbms") == ""


def test_chat_puts_context_in_the_system_prompt(tmp_path):
    seen = []

    class LLM:
        def chat(self, messages, tools=None):
            seen.append(messages[0]["content"])
            return ChatResult("ok")

    session = ChatSession(
        Agent(LLM(), ToolRegistry()),
        "I am Rosie.",
        now=lambda: datetime(2026, 11, 26, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        context=lambda message: f"## What you know\n- echo: {message}",
    )
    session.ask("dbms?")
    assert "## What you know\n- echo: dbms?" in seen[0]
    assert seen[0].index("Right now") < seen[0].index("What you know")
