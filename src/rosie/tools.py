"""Tool registry: the actions Rosie's agent loop is allowed to take.

Each tool has a JSON-schema for its arguments (sent to the LLM) and a risk tier
(used by the safety gate in the next step):

    read        look things up              -> run freely
    personal    write to rosie-vault         -> run, then tell the user
    external    affect the outside world     -> ask the user first
    system      touch the PC (apps, files)   -> allowlist + ask first
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["read", "personal", "external", "system"]

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ToolError(Exception):
    """A tool could not be found, its arguments were invalid, or it failed."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[..., Any]
    tier: Tier = "read"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )

    def schema(self) -> dict[str, Any]:
        """The OpenAI-format function schema sent to the LLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        props: dict[str, Any] = self.parameters.get("properties", {})
        for required in self.parameters.get("required", []):
            if required not in arguments:
                raise ToolError(f"{self.name}: missing argument '{required}'")
        for key, value in arguments.items():
            if key not in props:
                raise ToolError(f"{self.name}: unknown argument '{key}'")
            expected = _JSON_TYPES.get(props[key].get("type", ""))
            # bool is a subclass of int in Python; don't let True pass as an integer
            wrong_bool = isinstance(value, bool) and props[key].get("type") in {"integer", "number"}
            if expected is not None and (not isinstance(value, expected) or wrong_bool):
                raise ToolError(
                    f"{self.name}: '{key}' should be {props[key]['type']}, "
                    f"got {type(value).__name__}"
                )
            if "enum" in props[key] and value not in props[key]["enum"]:
                raise ToolError(f"{self.name}: '{key}' must be one of {props[key]['enum']}")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool
        return tool

    def tool(
        self,
        name: str,
        description: str,
        *,
        tier: Tier = "read",
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form: @registry.tool("get_time", "Current local time")."""

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            kwargs: dict[str, Any] = {}
            if parameters is not None:
                kwargs["parameters"] = parameters
            self.register(Tool(name, description, fn, tier, **kwargs))
            return fn

        return decorate

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"unknown tool '{name}'") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[n].schema() for n in self.names()]

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        """Validate and run a tool. Always returns text for the LLM to read."""
        tool = self.get(name)
        tool.validate(arguments)
        try:
            result = tool.handler(**arguments)
        except ToolError:
            raise
        except Exception as exc:  # a tool bug must not crash Rosie
            raise ToolError(f"{name} failed: {exc}") from exc
        return "" if result is None else str(result)
