"""`rosie doctor`: checks the setup from docs/SETUP-WINDOWS.md, one line per check.

    [ok]   Python 3.12
    [fail] Ollama: not reachable at http://localhost:11434/v1 (run `ollama serve`)

Exit code 0 if nothing failed (warnings are fine), 1 otherwise. It never prints
secret values, only whether the named environment variable is set.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import httpx

from rosie.config import LLMConfig, RosieConfig
from rosie.safety import DEFAULT_POLICY_PATH, PermissionPolicy

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str

    def line(self) -> str:
        return f"[{self.status}]".ljust(7) + f"{self.name}: {self.detail}"


def check_python(version: tuple[int, int] = sys.version_info[:2]) -> Check:
    text = f"{version[0]}.{version[1]}"
    if version >= (3, 11):
        return Check("Python", "ok", text)
    return Check("Python", "fail", f"{text} is too old; install Python 3.12")


def check_data_dir(config: RosieConfig) -> Check:
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        probe = config.data_dir / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("Data folder", "fail", f"can't write to {config.data_dir} ({exc})")
    return Check("Data folder", "ok", str(config.data_dir))


def check_llm(llm: LLMConfig, http: httpx.Client, label: str = "LLM") -> Check:
    """Ask the OpenAI-compatible /models endpoint and look for the configured model."""
    url = llm.base_url.rstrip("/") + "/models"
    try:
        response = http.get(url)
        response.raise_for_status()
        models = {m.get("id", "") for m in response.json().get("data", [])}
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        hint = " (run `ollama serve`)" if llm.provider == "ollama" else ""
        return Check(label, "fail", f"not reachable at {llm.base_url}{hint}: {exc}")
    if llm.model in models:
        return Check(label, "ok", f"{llm.model} at {llm.base_url}")
    hint = f" (run `ollama pull {llm.model}`)" if llm.provider == "ollama" else ""
    return Check(label, "fail", f"{llm.model} not found{hint}")


def check_api_key(llm: LLMConfig, environ: Mapping[str, str]) -> Check:
    if environ.get(llm.api_key_env or ""):
        return Check("Fallback key", "ok", f"{llm.api_key_env} is set")
    return Check("Fallback key", "warn", f"{llm.api_key_env} is not set in .env; fallback off")


def check_user_vault(config: RosieConfig) -> Check:
    if config.user_vault_dir is None:
        return Check("Your vault", "warn", "user_vault_dir not set; read_note won't work")
    if not config.user_vault_dir.is_dir():
        return Check("Your vault", "fail", f"{config.user_vault_dir} doesn't exist")
    return Check("Your vault", "ok", f"{config.user_vault_dir} (read only)")


def check_permissions(path=DEFAULT_POLICY_PATH) -> Check:
    policy = PermissionPolicy.load(path)
    if not policy.actions:
        return Check("Permissions", "warn", f"{path} unreadable; Rosie will ask before everything")
    return Check("Permissions", "ok", f"{len(policy.actions)} actions decided")


def run_checks(
    config: RosieConfig,
    http: httpx.Client | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[Check]:
    environ = os.environ if environ is None else environ
    http = http or httpx.Client(timeout=5.0)
    checks = [
        check_python(),
        check_data_dir(config),
        check_llm(config.llm, http),
    ]
    if config.fallback_llm is not None:
        if config.fallback_llm.api_key_env:
            checks.append(check_api_key(config.fallback_llm, environ))
        checks.append(Check("Fallback LLM", "ok", f"{config.fallback_llm.model} configured"))
    checks += [check_user_vault(config), check_permissions()]
    return checks


def report(checks: list[Check]) -> tuple[str, int]:
    lines = [c.line() for c in checks]
    failed = sum(c.status == "fail" for c in checks)
    lines.append("All good. Run `rosie chat`." if not failed else f"{failed} check(s) failed.")
    return "\n".join(lines), 1 if failed else 0
