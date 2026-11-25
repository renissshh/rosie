import json

import pytest

from rosie.agent import STEP_CAP_NOTICE, Agent, GateDecision, ToolCallLog
from rosie.llm import ChatResult, ToolCall
from rosie.tools import ToolRegistry


class ScriptedLLM:
    """Returns the scripted replies in order and records what it was sent."""

    def __init__(self, *replies: ChatResult) -> None:
        self.replies = list(replies)
        self.seen: list[tuple[list, list | None]] = []

    def chat(self, messages, tools=None):
        self.seen.append(([dict(m) for m in messages], tools))
        return self.replies.pop(0)


def call(name, args=None, id="c1"):
    return ChatResult(text=None, tool_calls=[ToolCall(id, name, args or {})])


@pytest.fixture
def registry():
    reg = ToolRegistry()

    @reg.tool("get_time", "Current time")
    def get_time():
        return "23:59"

    @reg.tool(
        "add_task",
        "Add a task",
        tier="personal",
        parameters={"type": "object", "properties": {"title": {"type": "string"}}},
    )
    def add_task(title):
        return f"added {title}"

    @reg.tool("broken", "Always fails")
    def broken():
        raise RuntimeError("disk full")

    return reg


def test_plain_answer_needs_no_tools(registry):
    llm = ScriptedLLM(ChatResult("Hi VinsmokE."))
    messages = [{"role": "user", "content": "hi"}]
    result = Agent(llm, registry).run(messages)
    assert result.text == "Hi VinsmokE."
    assert result.stopped == "answer"
    assert result.steps == []
    assert messages[-1] == {"role": "assistant", "content": "Hi VinsmokE."}
    # the model was offered every registered tool
    assert len(llm.seen[0][1]) == 3


def test_tool_call_then_answer(registry):
    llm = ScriptedLLM(call("get_time"), ChatResult("It's 23:59."))
    messages = [{"role": "user", "content": "time?"}]
    result = Agent(llm, registry).run(messages)

    assert result.text == "It's 23:59."
    assert [(s.tool, s.status, s.output) for s in result.steps] == [("get_time", "ok", "23:59")]
    # the second LLM call sees its own tool request and the tool's answer
    second = llm.seen[1][0]
    assert second[1]["role"] == "assistant"
    assert second[1]["tool_calls"][0]["function"]["name"] == "get_time"
    assert second[2] == {"role": "tool", "tool_call_id": "c1", "content": "23:59"}


def test_tool_errors_are_reported_to_the_model_not_raised(registry):
    llm = ScriptedLLM(
        call("broken", id="a"),
        call("fly", id="b"),
        call("add_task", {"title": 5}, id="c"),
        ChatResult("Sorry, that failed."),
    )
    result = Agent(llm, registry).run([{"role": "user", "content": "go"}])
    assert [s.status for s in result.steps] == ["error", "error", "error"]
    assert "disk full" in result.steps[0].output
    assert "unknown tool 'fly'" in result.steps[1].output
    assert "should be string" in result.steps[2].output
    assert result.text == "Sorry, that failed."


def test_step_cap_forces_an_answer(registry):
    llm = ScriptedLLM(
        call("get_time", id="1"), call("get_time", id="2"), ChatResult("Best guess: late.")
    )
    result = Agent(llm, registry, max_steps=2).run([{"role": "user", "content": "loop"}])
    assert result.stopped == "step_cap"
    assert result.text == "Best guess: late."
    assert len(result.steps) == 2
    final_messages, final_tools = llm.seen[-1]
    assert final_tools is None  # no tools on the forced answer
    assert final_messages[-1] == {"role": "system", "content": STEP_CAP_NOTICE}


def test_gate_refusal_is_logged_and_tool_not_run(registry):
    class DenyWrites:
        def check(self, tool, arguments):
            if tool.tier == "read":
                return GateDecision(True)
            return GateDecision(False, "writes need a yes")

    llm = ScriptedLLM(call("add_task", {"title": "x"}), ChatResult("I didn't add it."))
    result = Agent(llm, registry, gate=DenyWrites()).run([{"role": "user", "content": "add"}])
    step = result.steps[0]
    assert step.status == "refused"
    assert step.output == "refused: writes need a yes"  # add_task never ran
    assert llm.seen[1][0][-1]["content"] == "refused: writes need a yes"


def test_tool_call_log_is_json_lines(registry, tmp_path):
    path = tmp_path / "logs" / "tool_calls.jsonl"
    llm = ScriptedLLM(call("get_time"), call("broken", id="c2"), ChatResult("done"))
    Agent(llm, registry, call_log=ToolCallLog(path)).run([{"role": "user", "content": "x"}])
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(e["tool"], e["status"]) for e in lines] == [("get_time", "ok"), ("broken", "error")]
    assert {"arguments", "output", "duration_ms", "at"} <= set(lines[0])


def test_max_steps_must_be_positive(registry):
    with pytest.raises(ValueError):
        Agent(ScriptedLLM(), registry, max_steps=0)
