import shutil
import subprocess

import pytest

from rosie.vault import FOLDERS, GitSync, ensure_layout

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_layout_is_created(tmp_path):
    root = tmp_path / "rosie-vault"
    created = ensure_layout(root)
    for folder in FOLDERS:
        assert (root / folder / "README.md").is_file()
    assert (root / "README.md").is_file()
    assert len(created) == len(FOLDERS) + 1


def test_layout_never_overwrites(tmp_path):
    ensure_layout(tmp_path)
    (tmp_path / "memory" / "README.md").write_text("my edit", encoding="utf-8")
    assert ensure_layout(tmp_path) == []
    assert (tmp_path / "memory" / "README.md").read_text(encoding="utf-8") == "my edit"


@needs_git
def test_sync_without_remote_commits_locally(tmp_path):
    ensure_layout(tmp_path)
    result = GitSync(tmp_path).sync("rosie: set up vault")
    assert result.ok and result.committed and not result.pushed
    log = git("log", "--format=%an|%s", cwd=tmp_path).stdout.strip()
    assert log == "Rosie|rosie: set up vault"
    # nothing changed -> no empty commit
    assert GitSync(tmp_path).sync().committed is False


@needs_git
def test_sync_pushes_and_pulls_between_two_machines(tmp_path):
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    laptop = tmp_path / "laptop"
    ensure_layout(laptop)
    sync = GitSync(laptop)
    sync.init()
    git("remote", "add", "origin", str(remote), cwd=laptop)
    first = sync.sync("rosie: set up vault")
    assert first.ok and first.pushed

    server = tmp_path / "server"
    git("clone", str(remote), str(server), cwd=tmp_path)
    (server / "tasks" / "dbms.md").write_text("- [ ] revise DBMS", encoding="utf-8")
    assert GitSync(server).sync("rosie: add task").pushed

    (laptop / "daily" / "2026-11-26.md").write_text("Top 3: DBMS", encoding="utf-8")
    result = sync.sync("rosie: daily note")
    assert result.ok and result.pushed
    assert (laptop / "tasks" / "dbms.md").is_file()  # pulled the server's change


@needs_git
def test_offline_sync_keeps_the_local_commit(tmp_path):
    ensure_layout(tmp_path)
    sync = GitSync(tmp_path)
    sync.init()
    git("remote", "add", "origin", str(tmp_path / "missing.git"), cwd=tmp_path)
    result = sync.sync("rosie: offline")
    assert result.committed and not result.pushed
    assert "sync failed" in result.error
    assert git("log", "--format=%s", cwd=tmp_path).stdout.strip() == "rosie: offline"


def test_missing_git_is_reported_not_raised(tmp_path):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git not found")

    result = GitSync(tmp_path, run=no_git).sync()
    assert not result.ok and "git not found" in result.error


@needs_git
def test_cli_vault_sets_up_and_commits(tmp_path, monkeypatch, capsys):
    from rosie.__main__ import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    assert main(["vault"]) == 0
    out = capsys.readouterr().out
    assert "6 new files" in out and "committed locally" in out
    assert (tmp_path / "Rosie" / "rosie-vault" / "memory" / "README.md").is_file()
