import os
from datetime import datetime

import pytest

from rosie.__main__ import build_registry
from rosie.builtin_tools import MAX_NOTE_CHARS, UserVault, get_datetime
from rosie.config import RosieConfig
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.tools import ToolError


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "MyVault"
    (root / "Sem 3").mkdir(parents=True)
    (root / "Sem 3" / "DBMS.md").write_text("Normal forms: 1NF, 2NF, 3NF", encoding="utf-8")
    (root / "Sem 3" / "Networks.md").write_text("OSI has 7 layers", encoding="utf-8")
    (root / "Gym.md").write_text("Squat 5x5", encoding="utf-8")
    (root / "Old").mkdir()
    (root / "Old" / "Gym.md").write_text("old plan", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "Secret.md").write_text("app config", encoding="utf-8")
    (tmp_path / "outside.md").write_text("not yours", encoding="utf-8")
    return root


def test_get_datetime_formats_ist():
    fixed = lambda zone: datetime(2026, 11, 25, 23, 45, tzinfo=zone)  # noqa: E731
    text = get_datetime("Asia/Kolkata", fixed)
    assert text.startswith("Wednesday 25 Nov 2026, 23:45 IST")
    assert "2026-11-25T23:45:00+05:30" in text


def test_get_datetime_unknown_zone():
    with pytest.raises(ToolError, match="unknown time zone"):
        get_datetime("Mars/Olympus")


@pytest.mark.parametrize("name", ["Sem 3/DBMS.md", "Sem 3/DBMS", "DBMS", "dbms", "Sem 3\\DBMS"])
def test_read_note_by_path_or_name(vault, name):
    text = UserVault(vault).read(name)
    assert text == "# Sem 3/DBMS.md\n\nNormal forms: 1NF, 2NF, 3NF"


def test_ambiguous_name_lists_options(vault):
    # same result on case-insensitive Windows, where vault/gym.md "exists"
    with pytest.raises(ToolError, match="several notes.*Gym.md.*Old/Gym.md"):
        UserVault(vault).read("gym")
    assert "old plan" in UserVault(vault).read("Old/Gym")


def test_missing_note_suggests_close_names(vault):
    with pytest.raises(ToolError, match="Did you mean: Sem 3/Networks.md"):
        UserVault(vault).read("Network")


@pytest.mark.parametrize("name", ["../outside.md", "../outside", "Sem 3/../../outside.md"])
def test_cannot_escape_the_vault(vault, name):
    with pytest.raises(ToolError, match="outside your vault|no note"):
        UserVault(vault).read(name)


def test_absolute_paths_rejected(vault, tmp_path):
    with pytest.raises(ToolError, match="absolute"):
        UserVault(vault).read(str(tmp_path / "outside.md"))
    with pytest.raises(ToolError, match="absolute"):
        UserVault(vault).read("C:/Windows/win.ini")


def test_obsidian_folder_is_skipped(vault):
    assert all(".obsidian" not in p.parts for p in UserVault(vault).notes())


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_symlink_out_of_vault_is_refused(vault, tmp_path):
    try:
        (vault / "link.md").symlink_to(tmp_path / "outside.md")
    except OSError:
        pytest.skip("symlinks need admin rights on this Windows runner")
    with pytest.raises(ToolError, match="no note"):  # by name: hidden from the search
        UserVault(vault).read("link.md")
    (vault / "Sem 3" / "link.md").symlink_to(tmp_path / "outside.md")
    with pytest.raises(ToolError, match="outside your vault"):  # by path: refused
        UserVault(vault).read("Sem 3/link.md")
    assert "link" not in [p.stem for p in UserVault(vault).notes()]


def test_long_note_is_truncated(vault):
    (vault / "Big.md").write_text("x" * (MAX_NOTE_CHARS + 100), encoding="utf-8")
    assert UserVault(vault).read("Big").endswith("[... note truncated]")


def test_reading_never_changes_the_vault(vault):
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in vault.rglob("*") if p.is_file()}
    UserVault(vault).read("DBMS")
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in vault.rglob("*") if p.is_file()}
    assert before == after


def test_registered_tools_and_permissions(vault, tmp_path):
    config = RosieConfig(data_dir=tmp_path / "data", user_vault_dir=vault)
    reg = build_registry(config)
    assert reg.names() == ["get_datetime", "read_note"]
    assert "IST" in reg.call("get_datetime", {})
    assert "1NF" in reg.call("read_note", {"name": "DBMS"})
    gate = SafetyGate(PermissionPolicy.load())  # nobody to ask: only allow-listed tools run
    assert gate.check(reg.get("read_note"), {"name": "DBMS"}).allowed
    assert gate.check(reg.get("get_datetime"), {}).allowed


def test_read_note_without_vault_configured(tmp_path):
    reg = build_registry(RosieConfig(data_dir=tmp_path))
    with pytest.raises(ToolError, match="user_vault_dir"):
        reg.call("read_note", {"name": "DBMS"})
    reg = build_registry(RosieConfig(data_dir=tmp_path, user_vault_dir=tmp_path / "missing"))
    with pytest.raises(ToolError, match="doesn't exist"):
        reg.call("read_note", {"name": "DBMS"})
