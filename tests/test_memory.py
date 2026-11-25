import sqlite3
from contextlib import closing

import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.memory import Fact, FactError, FactStore, slug
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.tools import ToolError
from rosie.vault_writer import VaultWriter


@pytest.fixture
def store(tmp_path):
    vault = tmp_path / "rosie-vault"
    (vault / "memory").mkdir(parents=True)
    (vault / "memory" / "README.md").write_text("# memory\n", encoding="utf-8")
    return FactStore(VaultWriter(vault), tmp_path / "index" / "memory.db")


def note(store, topic):
    return (store.writer.root / "memory" / f"{topic}.md").read_text(encoding="utf-8")


def test_slug():
    assert slug("Study Plan!") == "study-plan"
    assert slug("  ") == "general"


def test_remember_writes_markdown_with_block_id(store):
    fact = store.remember("DBMS exam is on 12 Dec", "Study")
    assert fact.topic == "study" and len(fact.id) == 6
    assert note(store, "study") == f"# study\n\n- DBMS exam is on 12 Dec ^{fact.id}\n"


def test_remember_twice_is_not_duplicated(store):
    a = store.remember("Likes chai", "food")
    b = store.remember("  likes   CHAI ", "food")
    assert a == b
    assert note(store, "food").count("chai") == 1


def test_multiline_input_becomes_one_line(store):
    assert store.remember("gym\non\nMWF").text == "gym on MWF"


def test_empty_fact_rejected(store):
    with pytest.raises(FactError):
        store.remember("   ")


def test_update_keeps_id_and_other_lines(store):
    a = store.remember("Exam on 12 Dec", "study")
    b = store.remember("Weak at normalisation", "study")
    updated = store.update(a.id, "Exam moved to 14 Dec")
    assert updated == Fact(a.id, "study", "Exam moved to 14 Dec")
    assert store.all() == [updated, b]


def test_forget_removes_only_that_line(store):
    a = store.remember("Exam on 12 Dec", "study")
    b = store.remember("Weak at normalisation", "study")
    assert store.forget(a.id) == a
    assert store.all() == [b]
    assert "12 Dec" not in note(store, "study")
    with pytest.raises(FactError, match="no fact"):
        store.forget(a.id)


def test_users_own_edits_in_obsidian_count(store):
    path = store.writer.root / "memory" / "life.md"
    path.write_text("# life\nSome prose stays.\n- Sister is Ana\n", encoding="utf-8")
    facts = store.all()
    assert [f.text for f in facts] == ["Sister is Ana"]
    assert facts[0].id == store.all()[0].id  # derived id is stable
    store.update(facts[0].id, "Sister is Ana, lives in Pune")
    assert "Some prose stays." in note(store, "life")
    assert store.search("Pune")[0].text == "Sister is Ana, lives in Pune"


def test_readme_is_not_a_topic(store):
    store.remember("x", "general")
    assert store.topics() == ["general"]


def test_search_ranks_and_limits(store):
    store.remember("DBMS exam is on 12 Dec", "study")
    store.remember("Gym on Monday, Wednesday, Friday", "training")
    store.remember("DBMS notes are in Sem 3 folder", "study")
    hits = store.search("when is my dbms exam?")
    assert hits[0].text == "DBMS exam is on 12 Dec"
    assert {h.text for h in hits} == {"DBMS exam is on 12 Dec", "DBMS notes are in Sem 3 folder"}
    assert len(store.search("dbms", limit=1)) == 1
    assert store.search("?!") == []
    assert store.search("quantum") == []


def test_index_is_rebuildable(store):
    store.remember("Likes chai", "food")
    store.index_path.unlink()
    assert store.search("chai")[0].text == "Likes chai"
    assert store.reindex() == 1


def test_like_fallback_without_fts(store):
    store.remember("Likes chai", "food")
    store.remember("Hates coffee", "food")
    store._fts = False
    assert [f.text for f in store.search("chai")] == ["Likes chai"]


def test_index_matches_markdown(store):
    store.remember("Likes chai", "food")
    with closing(sqlite3.connect(store.index_path)) as db:
        assert db.execute("SELECT topic, text FROM facts").fetchall() == [("food", "Likes chai")]


def test_memory_tools_and_their_permissions(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path))
    out = reg.call("remember_fact", {"text": "DBMS exam on 12 Dec", "topic": "study"})
    fact_id = out[1:7]
    assert out == f"[{fact_id}] (study) DBMS exam on 12 Dec"
    assert (tmp_path / "rosie-vault" / "memory" / "study.md").is_file()
    assert "12 Dec" in reg.call("recall_facts", {"query": "dbms exam"})
    reg.call("update_fact", {"id": fact_id, "text": "DBMS exam on 14 Dec"})
    assert reg.call("forget_fact", {"id": fact_id}).startswith("forgot")
    assert reg.call("recall_facts", {"query": "dbms"}) == "nothing found"
    with pytest.raises(ToolError, match="no fact"):
        reg.call("forget_fact", {"id": "zzzzzz"})

    gate = SafetyGate(PermissionPolicy.load())
    assert gate.decision_for(reg.get("remember_fact")) == "ask"  # memory.write not decided yet
    assert gate.decision_for(reg.get("forget_fact")) == "allow"  # vault.rosie.delete
    assert gate.decision_for(reg.get("recall_facts")) == "allow"
