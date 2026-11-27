"""End to end in the terminal: the real `rosie` commands as separate processes.

A fresh data folder, the fake model (rosie_fakes.py), and the commands a new user runs
first: `rosie vault`, `rosie doctor`, `rosie chat` (typed through stdin, including the
safety gate's Allow? [y/N]), then `rosie brief`. No browser needed, so these run in
the normal test job on Ubuntu and Windows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rosie_fakes import clean_env, write_config


def rosie(data: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rosie", *args, "--config", str(data / "rosie.yaml")],
        input=stdin,
        cwd=data,  # no stray .env or config/ from the repo
        env=clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


@pytest.fixture
def data(tmp_path: Path, model_url: str) -> Path:
    write_config(tmp_path, model_url)
    return tmp_path


def test_first_run_vault_then_doctor(data: Path) -> None:
    vault = rosie(data, "vault")
    assert vault.returncode == 0, vault.stdout + vault.stderr
    assert "rosie-vault:" in vault.stdout
    for folder in ["daily", "tasks", "memory", "study-log", "training-log"]:
        assert (data / "rosie-vault" / folder).is_dir(), folder

    doctor = rosie(data, "doctor")
    assert "fake:e2e at http://127.0.0.1:" in doctor.stdout  # the model check passed
    assert doctor.returncode == 0, doctor.stdout
    assert "All good" in doctor.stdout


def test_chat_uses_tools_and_the_safety_gate_reads_your_answer(data: Path) -> None:
    typed = "\n".join(
        [
            "hello",
            "add a task: buy milk",
            "remember: I like tea",
            "n",  # Allow? [y/N] -> no
            "remember: I like coffee",
            "y",  # -> yes
            "/exit",
            "",
        ]
    )
    chat = rosie(data, "chat", stdin=typed)
    assert chat.returncode == 0, chat.stderr
    out = chat.stdout
    assert "Rosie: You said: hello" in out
    assert out.count("Allow? [y/N]") == 2
    assert "Rosie: Goodnight." in out

    tasks = (data / "rosie-vault" / "tasks" / "tasks.md").read_text(encoding="utf-8")
    assert "- [ ] buy milk" in tasks
    memory = "".join(
        p.read_text(encoding="utf-8") for p in (data / "rosie-vault" / "memory").glob("*.md")
    )
    assert "I like coffee" in memory
    assert "I like tea" not in memory


def test_brief_lists_what_chat_added(data: Path) -> None:
    rosie(data, "chat", stdin="add a task: submit DBMS assignment\n/exit\n")
    brief = rosie(data, "brief")
    assert brief.returncode == 0, brief.stderr
    assert "submit DBMS assignment" in brief.stdout


def test_chat_with_the_model_down_explains_and_keeps_going(tmp_path: Path) -> None:
    write_config(tmp_path, "http://127.0.0.1:9/v1")  # port 9: nothing listens
    chat = rosie(tmp_path, "chat", stdin="hello\n/exit\n")
    assert chat.returncode == 0
    assert "ollama serve" in chat.stdout
    assert "Rosie: Goodnight." in chat.stdout
