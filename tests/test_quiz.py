import random

import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.quiz import Fact, extract_facts, make_quiz, plain, quiz_text
from rosie.tools import ToolError

NOTE = """---
tags: [dbms]
---
# DBMS

## Normalisation
Organising tables to reduce redundancy. It has several normal forms.

- **1NF**: every column holds a single, atomic value
- [[2NF|Second normal form]] - no partial dependency on a composite key
- Primary key :: a column that uniquely identifies each row
- ok: short
- A very long bullet that is a sentence and not a term at all: and has a colon in it
- [ ] revise BCNF: before Friday

```sql
- SELECT: not a fact inside code
```

> Quote: not a fact either, it's a quote block

## Joins
- inner join - rows that match in both tables
"""


def test_plain_strips_markdown():
    assert plain("**bold** `code` [[Note|alias]] [[Other]] [x](http://y) #tag") == (
        "bold code alias Other x"
    )


def test_extract_facts_finds_the_usual_ways_of_writing_them():
    facts = extract_facts(NOTE)
    assert [f.term for f in facts] == [
        "Normalisation",
        "1NF",
        "Second normal form",
        "Primary key",
        "inner join",
    ]
    assert facts[0].answer == "Organising tables to reduce redundancy."
    assert facts[3].answer == "a column that uniquely identifies each row"
    assert facts[1].question() == "What is 1NF?"


def test_headings_followed_by_lists_are_not_facts():
    assert extract_facts("## Joins\n- inner join - rows that match in both") == [
        Fact("inner join", "rows that match in both")
    ]


def test_duplicate_terms_count_once():
    assert len(extract_facts("- Key: something long enough\n- key :: something else entirely")) == 1


def test_make_quiz_samples_without_repeats():
    facts = [Fact(f"t{i}", "answer long enough") for i in range(10)]
    quiz = make_quiz(facts, 5, random.Random(1))
    assert len(quiz) == 5 and len({f.term for f in quiz}) == 5
    assert len(make_quiz(facts, 50, random.Random(1))) == 10


def test_quiz_text_gives_questions_answers_and_rules():
    text = quiz_text("Sem 3/DBMS.md", NOTE, 3, random.Random(0))
    assert text.startswith("Quiz from Sem 3/DBMS.md: 3 of 5 facts. Ask ONE question at a time")
    assert text.count("| answer: ") == 3


def test_a_note_without_facts_goes_to_the_llm():
    text = quiz_text("Ideas.md", "Just some thoughts about life.", 4)
    assert "Write 4 short questions" in text
    assert text.endswith("Just some thoughts about life.")


def test_tool_reads_the_users_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Sem 3").mkdir(parents=True)
    (vault / "Sem 3" / "DBMS.md").write_text(NOTE, encoding="utf-8")
    reg = build_registry(RosieConfig(data_dir=tmp_path / "data", user_vault_dir=vault))
    tool = reg.get("quiz_from_note")
    assert tool.action == "vault.user.read" and tool.tier == "read"
    out = tool.handler(note="DBMS", count=2)
    assert out.startswith("Quiz from Sem 3/DBMS.md: 2 of 5")


def test_tool_without_a_vault_explains(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path))
    with pytest.raises(ToolError, match="user_vault_dir"):
        reg.get("quiz_from_note").handler(note="DBMS")
