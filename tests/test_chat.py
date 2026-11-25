from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from rosie.__main__ import find_config, main
from rosie.agent import Agent
from rosie.chat import ChatSession, build_session, make_asker, run_chat
from rosie.config import RosieConfig
from rosie.llm import ChatResult, LLMError, ToolCall
from rosie.tools import ToolRegistry

NIGHT = datetime(2026, 11, 25, 23, 45, tzinfo=ZoneInfo("Asia/Kolkata"))


class EchoLLM:
    """Answers 'you said: <last user message>' and records every request."""

    def __init__(self, fail=False):
        self.fail, self.requests = fail, []

    def chat(self, messages, tools=None):
        if self.fail:
            raise LLMError("ollama unreachable")
        self.requests.append([dict(m) for m in messages])
        last = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        return ChatResult(f"you said: {last}")


def session(llm=None, registry=None, **kw):
    agent = Agent(llm or EchoLLM(), registry or ToolRegistry())
    return ChatSession(agent, "I am Rosie.", now=lambda: NIGHT, **kw)


def scripted(*lines):
    it = iter(lines)

    def read(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return read


def test_history_carries_between_turns():
    llm = EchoLLM()
    s = session(llm)
    s.ask("my exam is DBMS")
    s.ask("what did I say?")
    second = llm.requests[1]
    assert second[0]["role"] == "system" and "23:45 IST" in second[0]["content"]
    assert [m["content"] for m in second[1:]] == [
        "my exam is DBMS",
        "you said: my exam is DBMS",
        "what did I say?",
    ]


def test_reset_forgets():
    s = session()
    s.ask("hello")
    s.reset()
    assert s.history == []


def test_trim_drops_whole_old_turns_and_keeps_tool_pairs():
    reg = ToolRegistry()
    reg.tool("get_time", "time")(lambda: "23:59")
    replies = iter(
        [ChatResult(None, [ToolCall("c", "get_time", {})]), ChatResult("23:59")]
        + [ChatResult("ok")] * 10
    )

    class LLM:
        def chat(self, messages, tools=None):
            return next(replies)

    s = session(LLM(), reg, max_messages=4)
    s.ask("time?")  # user, assistant(tool_calls), tool, assistant = 4 messages
    s.ask("thanks")  # +2 -> 6, must drop the whole first turn
    assert [m["role"] for m in s.history] == ["user", "assistant"]
    assert s.history[0]["content"] == "thanks"


def test_failed_turn_leaves_history_untouched():
    s = session(EchoLLM(fail=True))
    with pytest.raises(LLMError):
        s.ask("hi")
    assert s.history == []


def test_run_chat_commands_and_reply():
    out = []
    run_chat(session(), scripted("", "/help", "/tools", "hi Rosie", "/reset", "/exit"), out.append)
    assert out[0].startswith("Rosie: Evening, VinsmokE")
    assert "/reset" in out[1]
    assert out[2] == "Rosie: no tools yet"
    assert out[3] == "Rosie: you said: hi Rosie"
    assert out[4] == "Rosie: Fresh start."
    assert out[-1] == "Rosie: Goodnight."


def test_run_chat_survives_a_dead_model_and_eof():
    out = []
    run_chat(session(EchoLLM(fail=True)), scripted("hi"), out.append)
    assert "ollama serve" in out[1]
    assert "Goodnight" in out[-1]


@pytest.mark.parametrize(
    "answer, allowed", [("y", True), ("YES ", True), ("", False), ("n", False)]
)
def test_asker_defaults_to_no(answer, allowed):
    out = []
    assert make_asker(scripted(answer), out.append)("Send email?") is allowed
    assert out == ["Send email?"]


def test_asker_eof_is_no():
    assert make_asker(scripted(), lambda s: None)("ok?") is False


def test_build_session_wires_real_pieces(tmp_path):
    config = RosieConfig(data_dir=tmp_path)
    s = build_session(config, ToolRegistry(), scripted(), lambda s: None)
    assert s.agent.max_steps == config.max_agent_steps
    assert s.agent.call_log.path == tmp_path / "logs" / "tool_calls.jsonl"
    assert "VinsmokE" in s.soul


def test_find_config_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert find_config(None, {}) is None
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rosie.yaml").write_text("{}", encoding="utf-8")
    assert find_config(None, {}).name == "rosie.yaml"
    assert str(find_config(None, {"ROSIE_CONFIG": "x.yaml"})) == "x.yaml"
    assert str(find_config("a.yaml", {"ROSIE_CONFIG": "x.yaml"})) == "a.yaml"


def test_main_without_command_prints_hint(capsys):
    assert main([]) == 0
    assert "rosie chat" in capsys.readouterr().out
