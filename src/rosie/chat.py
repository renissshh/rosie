"""Terminal chat: `rosie chat`.

`ChatSession` keeps the conversation history and rebuilds the system prompt on
every turn (so the clock in it is always current). `run_chat` is the
read-eval-print loop; input and output are passed in so tests can drive it.

Commands: /help, /tools, /reset, /exit
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from rosie.agent import Agent, AgentResult, ToolCallLog
from rosie.config import RosieConfig
from rosie.llm import LLMError, build_llm
from rosie.logging_setup import setup_logging
from rosie.prompt import build_system_prompt, load_soul, now_in
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.tools import ToolRegistry

Reader = Callable[[str], str]
Writer = Callable[[str], None]

HELP = """Commands:
  /tools   list what I can do
  /reset   forget this conversation
  /exit    leave (Ctrl+C works too)"""


class ChatSession:
    def __init__(
        self,
        agent: Agent,
        soul: str,
        timezone: str = "Asia/Kolkata",
        max_messages: int = 40,
        now: Callable[[], datetime] | None = None,
        context: Callable[[str], str] | None = None,
    ) -> None:
        self.agent = agent
        self.soul = soul
        self.max_messages = max_messages
        self._now = now or (lambda: now_in(timezone))
        self.context = context
        self.history: list[dict[str, Any]] = []

    def system_prompt(self, message: str = "") -> str:
        extra = self.context(message) if self.context else ""
        return build_system_prompt(self.soul, self._now(), self.agent.registry.names(), extra)

    def ask(self, text: str) -> AgentResult:
        messages = [{"role": "system", "content": self.system_prompt(text)}, *self.history]
        messages.append({"role": "user", "content": text})
        # If the model fails (LLMError), history is left untouched: no half-finished turn.
        result = self.agent.run(messages)
        self.history = messages[1:]
        self._trim()
        return result

    def reset(self) -> None:
        self.history.clear()

    def _trim(self) -> None:
        """Drop the oldest whole turns, never splitting a tool call from its result."""
        while len(self.history) > self.max_messages:
            next_user = next(
                (i for i, m in enumerate(self.history) if i > 0 and m["role"] == "user"),
                None,
            )
            if next_user is None:  # a single huge turn: keep it
                return
            del self.history[:next_user]


def make_asker(read: Reader, write: Writer) -> Callable[[str], bool]:
    """The safety gate's yes/no question, asked in the terminal. Default is no."""

    def ask(question: str) -> bool:
        write(question)
        try:
            answer = read("Allow? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in {"y", "yes"}

    return ask


def run_chat(session: ChatSession, read: Reader = input, write: Writer = print) -> None:
    write("Rosie: Evening, VinsmokE. Type /help for commands.")
    while True:
        try:
            text = read("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            write("\nRosie: Goodnight.")
            return
        if not text:
            continue
        if text in {"/exit", "/quit"}:
            write("Rosie: Goodnight.")
            return
        if text == "/help":
            write(HELP)
            continue
        if text == "/reset":
            session.reset()
            write("Rosie: Fresh start.")
            continue
        if text == "/tools":
            names = session.agent.registry.names()
            write("Rosie: " + (", ".join(names) if names else "no tools yet"))
            continue
        try:
            result = session.ask(text)
        except LLMError as exc:
            write(f"Rosie: I can't reach my brain ({exc}). Is Ollama running? Try `ollama serve`.")
            continue
        write(f"Rosie: {result.text}")


def build_session(
    config: RosieConfig,
    registry: ToolRegistry,
    read: Reader = input,
    write: Writer = print,
    context: Callable[[str], str] | None = None,
) -> ChatSession:
    """Wire the real pieces together: local-first LLM, safety gate, tool log, persona."""
    setup_logging(config.logs_dir, console_level=logging.WARNING)
    agent = Agent(
        build_llm(config.llm, config.fallback_llm),
        registry,
        max_steps=config.max_agent_steps,
        gate=SafetyGate(PermissionPolicy.load(), make_asker(read, write)),
        call_log=ToolCallLog(config.logs_dir / "tool_calls.jsonl"),
    )
    return ChatSession(agent, load_soul(config.data_dir), config.timezone, context=context)
