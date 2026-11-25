"""Safety gate: decides, before every tool call, whether Rosie may act.

The user's decisions live in config/permissions.yaml (docs/decisions/0001):

    allow -> run          ask -> ask the user, run only on a yes          deny -> never

How a call is decided:
1. The tool's `action` is looked up in the policy. Unknown action -> "ask".
2. Tools with no action: read-tier tools (pure lookups such as the clock) run;
   any other tier is "ask".
3. The tool's tier sets a floor: "external" and "system" tools are at least
   "ask", even if someone edits the YAML to "allow". "deny" always wins.
4. If the policy file is missing or broken, every action is "ask" (fail closed).
5. "ask" with nobody to ask (no prompt function) is treated as "no".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from rosie.agent import GateDecision
from rosie.tools import Tool

log = logging.getLogger("rosie.safety")

Decision = Literal["allow", "ask", "deny"]
_RANK: dict[str, int] = {"allow": 0, "ask": 1, "deny": 2}
_TIER_FLOOR: dict[str, Decision] = {
    "read": "allow",
    "personal": "allow",
    "external": "ask",
    "system": "ask",
}

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "permissions.yaml"


def _stricter(a: Decision, b: Decision) -> Decision:
    return a if _RANK[a] >= _RANK[b] else b


@dataclass(frozen=True)
class PermissionPolicy:
    actions: Mapping[str, Decision] = field(default_factory=dict)
    default: Decision = "ask"

    @classmethod
    def load(cls, path: Path = DEFAULT_POLICY_PATH) -> PermissionPolicy:
        """Read permissions.yaml. Any problem gives an empty policy: everything is "ask"."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            raw = data["actions"]
            if not isinstance(raw, dict):
                raise TypeError("'actions' must be a mapping")
        except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
            log.error("permissions unreadable (%s); every action will need a yes", exc)
            return cls()
        actions: dict[str, Decision] = {}
        for name, value in raw.items():
            if value in _RANK:
                actions[str(name)] = value
            else:
                log.error("permissions: %s has unknown value %r; treating as ask", name, value)
                actions[str(name)] = "ask"
        return cls(actions)

    def decide(self, action: str) -> Decision:
        return self.actions.get(action, self.default)


def describe_call(tool: Tool, arguments: dict[str, Any]) -> str:
    """One readable line for the yes/no question."""
    args = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    return f"Rosie wants to {tool.description.rstrip('.').lower()}: {tool.name}({args})"


class SafetyGate:
    def __init__(
        self,
        policy: PermissionPolicy,
        ask_user: Callable[[str], bool] | None = None,
    ) -> None:
        self.policy = policy
        self.ask_user = ask_user

    def decision_for(self, tool: Tool) -> Decision:
        if tool.action is not None:
            decision = self.policy.decide(tool.action)
        else:
            decision = "allow" if tool.tier == "read" else "ask"
        return _stricter(decision, _TIER_FLOOR.get(tool.tier, "ask"))

    def check(self, tool: Tool, arguments: dict[str, Any]) -> GateDecision:
        decision = self.decision_for(tool)
        label = tool.action or tool.name
        if decision == "allow":
            return GateDecision(True, f"{label} is allowed")
        if decision == "deny":
            return GateDecision(False, f"{label} is never allowed (config/permissions.yaml)")
        if self.ask_user is None:
            return GateDecision(False, f"{label} needs the user's yes and nobody could be asked")
        if self.ask_user(describe_call(tool, arguments)):
            return GateDecision(True, "the user said yes")
        return GateDecision(False, "the user said no")
