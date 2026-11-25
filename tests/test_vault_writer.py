"""Invariant 1: Rosie never writes outside rosie-vault."""

import os

import pytest

from rosie.vault_writer import VaultPathError, VaultWriter


@pytest.fixture
def setup(tmp_path):
    vault = tmp_path / "Rosie" / "rosie-vault"
    vault.mkdir(parents=True)
    (vault / ".git").mkdir()
    user = tmp_path / "MyVault"
    user.mkdir()
    (user / "DBMS.md").write_text("mine", encoding="utf-8")
    return tmp_path, vault, user


def snapshot(folder):
    return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_write_append_read_delete(setup):
    _, vault, _ = setup
    w = VaultWriter(vault)
    path = w.write("tasks/dbms.md", "- [ ] revise normal forms")
    assert path == vault / "tasks" / "dbms.md"
    w.append("tasks/dbms.md", "- [ ] past papers\n")
    assert w.read("tasks/dbms.md") == "- [ ] revise normal forms\n- [ ] past papers\n"
    assert w.delete("tasks/dbms.md") is True
    assert w.delete("tasks/dbms.md") is False


def test_windows_separators_work(setup):
    _, vault, _ = setup
    VaultWriter(vault).write("daily\\2026-11-26.md", "Top 3")
    assert (vault / "daily" / "2026-11-26.md").is_file()


def test_no_temp_files_left_behind(setup):
    _, vault, _ = setup
    VaultWriter(vault).write("memory/facts.md", "likes chai")
    assert [p.name for p in (vault / "memory").iterdir()] == ["facts.md"]


ESCAPES = [
    "../escape.md",
    "..\\escape.md",
    "tasks/../../escape.md",
    "/etc/escape.md",
    "C:/Windows/escape.md",
    "C:escape.md",
    "\\\\server\\share\\escape.md",
    "../MyVault/DBMS.md",
    "../../MyVault/DBMS.md",
    ".git/config.md",
    ".git/hooks/pre-commit",
    "tasks/notes.txt",
    "tasks/script.py",
    "",
    ".",
]


@pytest.mark.parametrize("rel", ESCAPES)
def test_every_escape_is_refused_and_nothing_changes(setup, rel):
    tmp_path, vault, user = setup
    before = snapshot(tmp_path)
    w = VaultWriter(vault, forbidden=[user])
    for op in (lambda: w.write(rel, "x"), lambda: w.append(rel, "x"), lambda: w.delete(rel)):
        with pytest.raises(VaultPathError):
            op()
    assert snapshot(tmp_path) == before


def test_symlinked_folder_out_of_vault_is_refused(setup):
    tmp_path, vault, user = setup
    try:
        os.symlink(user, vault / "sneaky", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need admin rights on this Windows runner")
    before = snapshot(user)
    with pytest.raises(VaultPathError, match="outside"):
        VaultWriter(vault).write("sneaky/DBMS.md", "overwritten")
    assert snapshot(user) == before


def test_forbidden_folder_is_refused_even_inside_root(setup):
    # belt and braces: the config already refuses overlapping vaults
    _, vault, _ = setup
    inner = vault / "mirror"
    inner.mkdir()
    with pytest.raises(VaultPathError, match="read only"):
        VaultWriter(vault, forbidden=[inner]).write("mirror/x.md", "x")
