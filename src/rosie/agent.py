"""The agent loop: ask the model, run the tools it asks for, repeat.

    user message -> LLM -> tool calls? -> run each tool -> LLM -> ... -> answer

Two limits keep it safe and cheap:
- a step cap (`max_steps`): after that many tool rounds the model must answer
  with what it has, so a confused model can't loop forever;
- a gate (see `rosie.safety`), asked before every tool call. A refused call is
  reported back to the model as text, so it can explain or try something else.

Every tool call is recorded in a log (`AgentResult.steps`), and optionally
appended to a JSON-lines file so the user can audit what Rosie did.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from rosie.llm import ChatModel, ToolCall
from rosie.tools import Tool, ToolError, ToolRegistry

log = logging.getLogger("rosie.agent")

STEP_CAP_NOTICE = (
    "You have used all your tool steps for this request. "
    "Answer the user now with what you already know."
)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str = ""


class Gate(Protocol):
    def check(self, tool: Tool, arguments: dict[str, Any]) -> GateDecision: ...


class AllowAll:
    """Gate for tests and read-only setups. The real one is `rosie.safety.SafetyGate`."""

    def check(self, tool: Tool, arguments: dict[str, Any]) -> GateDecision:
        return GateDecision(True, "no gate")


@dataclass
class ToolStep:
    """One entry in the tool-call log."""

    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "error", "refused"]
    output: str
    duration_ms: int = 0
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


@dataclass
class AgentResult:
    text: str
    steps: list[ToolStep]
    stopped: Literal["answer", "step_cap"]


class ToolCallLog:
    """Appends each tool step as one JSON line (e.g. D:\\Rosie\\logs\\tool_calls.jsonl)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, step: ToolStep) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(step), ensure_ascii=False) + "\n")


def _assistant_message(text: str | None, calls: list[ToolCall]) -> dict[str, Any]:
    """The model's tool request, echoed back in OpenAI format so it sees its own calls."""
    return {
        "role": "assistant",
        "content": text or "",
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for c in calls
        ],
    }


class Agent:
    def __init__(
        self,
        llm: ChatModel,
        registry: ToolRegistry,
        *,
        max_steps: int = 8,
        gate: Gate | None = None,
        call_log: ToolCallLog | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps
        self.gate = gate or AllowAll()
        self.call_log = call_log
        self._clock = clock

    def run(self, messages: list[dict[str, Any]]) -> AgentResult:
        """Run until the model answers. `messages` is extended in place with the turn."""
        steps: list[ToolStep] = []
        tools = self.registry.schemas() or None
        for _ in range(self.max_steps):
            result = self.llm.chat(messages, tools)
            if not result.tool_calls:
                text = result.text or ""
                messages.append({"role": "assistant", "content": text})
                return AgentResult(text, steps, "answer")
            messages.append(_assistant_message(result.text, result.tool_calls))
            for call in result.tool_calls:
                step = self._run_tool(call)
                steps.append(step)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": step.output})

        # Step cap reached: one last call with no tools, so the model has to answer.
        log.warning("step cap of %d reached", self.max_steps)
        messages.append({"role": "system", "content": STEP_CAP_NOTICE})
        text = self.llm.chat(messages, None).text or ""
        messages.append({"role": "assistant", "content": text})
        return AgentResult(text, steps, "step_cap")

    def _run_tool(self, call: ToolCall) -> ToolStep:
        start = self._clock()
        try:
            tool = self.registry.get(call.name)
            tool.validate(call.arguments)
            decision = self.gate.check(tool, call.arguments)
            if not decision.allowed:
                step = ToolStep(call.name, call.arguments, "refused", f"refused: {decision.reason}")
            else:
                output = self.registry.call(call.name, call.arguments)
                step = ToolStep(call.name, call.arguments, "ok", output)
        except ToolError as exc:
            step = ToolStep(call.name, call.arguments, "error", f"error: {exc}")
        step.duration_ms = int((self._clock() - start) * 1000)
        log.info("tool %s -> %s", call.name, step.status)
        if self.call_log is not None:
            self.call_log.write(step)
        return step
