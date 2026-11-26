"""Quizzes from your own notes: "quiz me on DBMS".

Rosie reads the note (read only, from your vault) and picks out facts written in the
ways people usually write them in Obsidian:

    Primary key :: a column that uniquely identifies a row     (spaced-repetition style)
    - **2NF**: no partial dependency on a composite key         (bold term, colon)
    - Deadlock - processes each waiting on the other            (term, dash)
    ## Normalisation                                            (heading, then its
    Organising tables to reduce redundancy. ...                  first sentence)

Each fact becomes a question ("What is 2NF?") with its answer. The agent asks them one at
a time and checks your replies. The questions are picked at random, so every quiz is a
little different; tests pass a seeded random generator.

A note with no such lines still works: the tool hands the agent the note's text and asks
it to write the questions itself.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

MAX_TERM_WORDS = 6
MIN_ANSWER_CHARS = 8
NOTE_FOR_LLM_CHARS = 4000

_CLOZE = re.compile(r"^(?:[-*+]\s+)?(.+?)\s*::\s*(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(.+?)\s*(?::|\s[-–—]\s)\s*(.+)$")
_HEADING = re.compile(r"^#{2,6}\s+(.+?)\s*#*$")
_SENTENCE = re.compile(r"^(.+?[.!?])(?:\s|$)")


@dataclass(frozen=True)
class Fact:
    term: str
    answer: str

    def question(self) -> str:
        return f"What is {self.term}?"


def plain(text: str) -> str:
    """Strip the Markdown that shouldn't be read out: bold, code, [[links|alias]], tags."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"(?<!\w)#[\w/-]+", "", text)
    return " ".join(text.split())


def _fact(term: str, answer: str) -> Fact | None:
    term, answer = plain(term).rstrip(":"), plain(answer)
    if not term or len(term.split()) > MAX_TERM_WORDS or len(answer) < MIN_ANSWER_CHARS:
        return None
    if term.lower().startswith(("http", "[ ]", "[x]")):
        return None
    return Fact(term, answer)


def extract_facts(markdown: str) -> list[Fact]:
    facts: list[Fact] = []
    lines = markdown.splitlines()
    in_code = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith(("---", ">", "|")):
            continue
        fact = None
        if (match := _CLOZE.match(line)) or (match := _BULLET.match(line)):
            fact = _fact(*match.groups())
        elif match := _HEADING.match(line):
            body = next((n.strip() for n in lines[i + 1 :] if n.strip()), "")
            sentence = _SENTENCE.match(plain(body))
            if sentence and not body.startswith(("#", "-", "*", "|", "```")):
                fact = _fact(match.group(1), sentence.group(1))
        if fact and all(f.term.lower() != fact.term.lower() for f in facts):
            facts.append(fact)
    return facts


def make_quiz(facts: list[Fact], count: int, rng: random.Random | None = None) -> list[Fact]:
    rng = rng or random.Random()
    return rng.sample(facts, min(count, len(facts)))


def quiz_text(title: str, markdown: str, count: int = 5, rng: random.Random | None = None) -> str:
    """What the quiz tool returns to the agent: questions with answers, and how to run it."""
    facts = extract_facts(markdown)
    if not facts:
        excerpt = markdown[:NOTE_FOR_LLM_CHARS]
        return (
            f"No term/definition lines found in {title}. Write {count} short questions "
            "from the note below, ask them one at a time, and check each answer.\n\n" + excerpt
        )
    picked = make_quiz(facts, count, rng)
    lines = [
        f"Quiz from {title}: {len(picked)} of {len(facts)} facts. Ask ONE question at a time, "
        "wait for the answer, say if it's right (be generous with wording), then the next. "
        "Don't show the answers before the user replies. End with the score.",
    ]
    lines += [f"{n}. {f.question()} | answer: {f.answer}" for n, f in enumerate(picked, 1)]
    return "\n".join(lines)


def register_quiz_tool(registry, config) -> None:
    """quiz_from_note reads your vault (read only, "vault.user.read": allowed)."""
    from rosie.builtin_tools import UserVault
    from rosie.tools import Tool, ToolError

    def quiz_from_note(note: str, count: int = 5) -> str:
        if config.user_vault_dir is None or not config.user_vault_dir.is_dir():
            raise ToolError("your vault isn't set up yet: add user_vault_dir to rosie.yaml")
        vault = UserVault(config.user_vault_dir)
        path = vault.find(note)
        text = path.read_text(encoding="utf-8", errors="replace")
        return quiz_text(vault.rel(path), text, max(1, min(int(count), 20)))

    registry.register(
        Tool(
            "quiz_from_note",
            "Quiz the user on one of their notes: returns questions with answers to ask one by one",
            quiz_from_note,
            "read",
            {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Note name like 'DBMS'"},
                    "count": {"type": "integer", "description": "How many questions (default 5)"},
                },
                "required": ["note"],
            },
            action="vault.user.read",
        )
    )
