"""Rosie configuration.

Precedence, lowest to highest:
    built-in defaults  <  rosie.yaml  <  environment variables (ROSIE_*)

On Windows all runtime data defaults to D:\\Rosie (the user's data drive).
Secrets (API keys, Telegram token) never live in YAML: only in `.env` or the
real environment, referenced by variable name.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

WINDOWS_DATA_DIR = Path("D:/Rosie")


def default_data_dir(platform: str = sys.platform) -> Path:
    """D:\\Rosie on Windows; ~/.rosie everywhere else (CI, servers)."""
    if platform.startswith("win"):
        return WINDOWS_DATA_DIR
    return Path.home() / ".rosie"


class LLMConfig(BaseModel):
    """One LLM endpoint. Both supported providers speak the OpenAI chat format."""

    provider: Literal["ollama", "openai_compatible"] = "ollama"
    model: str = "qwen3:8b"
    base_url: str = "http://localhost:11434/v1"
    api_key_env: str | None = None  # name of the env var holding the key, never the key
    timeout_s: float = 120.0


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
BlockKind = Literal["study", "college", "gym", "review", "sleep", "other"]


class DayBlock(BaseModel):
    """One block of the usual day, drawn on the orb's Day Ring. Times are local HH:MM;
    a block may cross midnight (sleep 23:30 -> 06:30)."""

    start: str
    end: str
    kind: BlockKind = "other"
    label: str = ""
    days: list[str] = Field(default_factory=lambda: list(WEEKDAYS))

    @field_validator("start", "end")
    @classmethod
    def _clock(cls, value: str) -> str:
        hour, sep, minute = value.partition(":")
        if not (sep and hour.isdigit() and minute.isdigit() and len(minute) == 2):
            raise ValueError(f"time must be HH:MM, got {value!r}")
        if int(hour) > 23 or int(minute) > 59:
            raise ValueError(f"no such time {value!r}")
        return f"{int(hour):02d}:{minute}"

    @field_validator("days")
    @classmethod
    def _days(cls, value: list[str]) -> list[str]:
        days = [d.strip().lower()[:3] for d in value]
        unknown = [d for d in days if d not in WEEKDAYS]
        if unknown:
            raise ValueError(f"unknown day(s) {unknown}; use mon..sun")
        return days


class Countdown(BaseModel):
    """A date to count down to on the Command Deck (exams, a deadline)."""

    label: str
    date: date


class RosieConfig(BaseModel):
    data_dir: Path = Field(default_factory=default_data_dir)
    vault_dir: Path | None = None  # Rosie's own vault; defaults to <data_dir>/rosie-vault
    user_vault_dir: Path | None = None  # the user's Obsidian vault, READ ONLY
    timezone: str = "Asia/Kolkata"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    fallback_llm: LLMConfig | None = None
    max_agent_steps: int = 8
    brief_time: str = "07:30"  # morning brief, local time (HH:MM)
    review_time: str = "22:00"  # nightly review
    voice: str = "kokoro-emma"  # see `rosie voices`
    day_blocks: list[DayBlock] = Field(default_factory=list)  # the orb's Day Ring
    countdowns: list[Countdown] = Field(default_factory=list)  # shown on the Command Deck
    subjects: list[str] = Field(default_factory=list)  # for the study coach, e.g. [DBMS, OS]
    # Which machine sends the morning brief and nightly review: "here", or "server" when
    # an always-on `rosie server` does it (then this laptop doesn't, so nothing doubles).
    clock: Literal["here", "server"] = "here"
    vault_sync_minutes: int = Field(default=10, ge=1)  # git pull/push of rosie-vault

    @model_validator(mode="after")
    def _derive_paths(self) -> RosieConfig:
        if self.vault_dir is None:
            self.vault_dir = self.data_dir / "rosie-vault"
        if self.user_vault_dir is not None and _same_or_nested(self.vault_dir, self.user_vault_dir):
            raise ValueError(
                "rosie-vault must be separate from your own vault "
                f"({self.vault_dir} overlaps {self.user_vault_dir})"
            )
        return self

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def _same_or_nested(a: Path, b: Path) -> bool:
    a, b = Path(os.path.abspath(a)), Path(os.path.abspath(b))
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, # comments, optional quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(path: Path, environ: dict[str, str] | None = None) -> None:
    """Load .env into the environment without overriding variables already set."""
    environ = os.environ if environ is None else environ
    if not path.is_file():
        return
    for key, value in parse_dotenv(path.read_text(encoding="utf-8")).items():
        environ.setdefault(key, value)


_ENV_OVERRIDES = {
    "ROSIE_DATA_DIR": ("data_dir",),
    "ROSIE_VAULT_DIR": ("vault_dir",),
    "ROSIE_USER_VAULT_DIR": ("user_vault_dir",),
    "ROSIE_TIMEZONE": ("timezone",),
    "ROSIE_LLM_PROVIDER": ("llm", "provider"),
    "ROSIE_LLM_MODEL": ("llm", "model"),
    "ROSIE_LLM_BASE_URL": ("llm", "base_url"),
}


def load_config(
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RosieConfig:
    """Build the config from defaults, an optional YAML file and ROSIE_* env vars."""
    environ = os.environ if environ is None else environ
    data: dict = {}
    if path is not None and path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
    for var, keys in _ENV_OVERRIDES.items():
        if var in environ:
            target = data
            for key in keys[:-1]:
                target = target.setdefault(key, {})
            target[keys[-1]] = environ[var]
    return RosieConfig.model_validate(data)
