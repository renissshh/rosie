from datetime import datetime
from zoneinfo import ZoneInfo

from rosie.prompt import (
    FALLBACK_SOUL,
    MAX_SOUL_CHARS,
    REPO_SOUL,
    build_system_prompt,
    format_now,
    load_soul,
    now_in,
)

IST = ZoneInfo("Asia/Kolkata")
NIGHT = datetime(2026, 11, 25, 23, 45, tzinfo=IST)


def test_repo_soul_exists_and_names_the_user():
    soul = load_soul(None)
    assert soul.startswith("# Rosie")
    assert "VinsmokE" in soul
    assert "read only" in soul


def test_users_own_soul_wins(tmp_path):
    (tmp_path / "SOUL.md").write_text("You are Rosie, but pirate.", encoding="utf-8")
    assert load_soul(tmp_path) == "You are Rosie, but pirate."


def test_empty_user_soul_falls_back_to_repo(tmp_path):
    (tmp_path / "SOUL.md").write_text("  \n", encoding="utf-8")
    assert load_soul(tmp_path) == REPO_SOUL.read_text(encoding="utf-8").strip()


def test_missing_everything_uses_fallback(tmp_path):
    assert load_soul(tmp_path, repo_soul=tmp_path / "nope.md") == FALLBACK_SOUL


def test_long_soul_is_capped(tmp_path):
    (tmp_path / "SOUL.md").write_text("x" * (MAX_SOUL_CHARS + 50), encoding="utf-8")
    assert len(load_soul(tmp_path)) == MAX_SOUL_CHARS


def test_format_now_is_ist():
    assert format_now(NIGHT) == "Wednesday 25 Nov 2026, 23:45 IST (Asia/Kolkata)"


def test_prompt_has_soul_time_and_tools():
    prompt = build_system_prompt("I am Rosie.", NIGHT, ["get_datetime", "read_note"])
    assert prompt.startswith("I am Rosie.")
    assert "It is Wednesday 25 Nov 2026, 23:45 IST" in prompt
    assert "get_datetime, read_note" in prompt


def test_prompt_without_tools_says_so():
    assert "None yet" in build_system_prompt("I am Rosie.", NIGHT)


def test_now_in_uses_the_zone():
    assert now_in("Asia/Kolkata").utcoffset().total_seconds() == 5.5 * 3600
