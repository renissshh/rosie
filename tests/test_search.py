import pytest

from rosie.__main__ import build_registry
from rosie.config import RosieConfig
from rosie.safety import PermissionPolicy, SafetyGate
from rosie.search import NoteIndex, iter_notes


@pytest.fixture
def vaults(tmp_path):
    user = tmp_path / "MyVault"
    (user / "Sem 3").mkdir(parents=True)
    (user / "Sem 3" / "DBMS.md").write_text("Normalisation: 1NF removes repeating groups.")
    (user / "Gym.md").write_text("Squat 5x5 on Monday")
    (user / ".obsidian").mkdir()
    (user / ".obsidian" / "workspace.md").write_text("normalisation config noise")
    rosie = tmp_path / "rosie-vault"
    (rosie / "memory").mkdir(parents=True)
    (rosie / "memory" / "study.md").write_text("- Weak at normalisation ^abc123")
    return tmp_path, user, rosie


@pytest.fixture
def index(vaults):
    tmp_path, user, rosie = vaults
    return NoteIndex(tmp_path / "index" / "notes.db", {"yours": user, "rosie": rosie})


def snapshot(folder):
    return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.rglob("*") if p.is_file()}


def test_search_across_both_vaults(index):
    hits = index.search("normalisation")
    assert {(h.vault, h.path) for h in hits} == {
        ("yours", "Sem 3/DBMS.md"),
        ("rosie", "memory/study.md"),
    }
    dbms = next(h for h in hits if h.vault == "yours")
    assert "**Normalisation**" in dbms.snippet


def test_filter_by_vault(index):
    assert [h.path for h in index.search("normalisation", vault="rosie")] == ["memory/study.md"]


def test_title_is_searchable(index):
    assert index.search("gym")[0].path == "Gym.md"


def test_app_folders_skipped(vaults):
    _, user, _ = vaults
    assert ".obsidian" not in {p.parent.name for p in iter_notes(user)}


def test_refresh_is_incremental_and_tracks_changes(vaults, index):
    _, user, _ = vaults
    assert index.refresh() == 3
    assert index.refresh() == 0  # nothing changed
    (user / "Gym.md").write_text("Deadlift 3x5 on Friday, longer text now")
    (user / "Sem 3" / "DBMS.md").unlink()
    assert index.refresh() == 1
    assert index.search("deadlift")[0].path == "Gym.md"
    assert index.search("squat") == []
    assert index.search("repeating") == []


def test_index_never_touches_the_vaults(vaults, index):
    tmp_path, user, rosie = vaults
    before = snapshot(user), snapshot(rosie)
    index.search("normalisation")
    assert (snapshot(user), snapshot(rosie)) == before
    assert index.index_path.is_relative_to(tmp_path / "index")


def test_empty_or_odd_queries(index):
    assert index.search("?!") == []
    assert index.search('"; DROP TABLE notes; --') == []
    assert len(index.search("normalisation", limit=1)) == 1


def test_missing_vault_folder_is_fine(tmp_path):
    index = NoteIndex(tmp_path / "i.db", {"yours": tmp_path / "gone"})
    assert index.search("anything") == []


def test_tool_is_registered_and_allowed(vaults):
    tmp_path, user, _ = vaults
    reg = build_registry(RosieConfig(data_dir=tmp_path / "data", user_vault_dir=user))
    out = reg.call("search_notes", {"query": "squat"})
    assert out.startswith("[yours] Gym.md:")
    assert reg.call("search_notes", {"query": "squat", "vault": "rosie"}) == "no notes match"
    assert SafetyGate(PermissionPolicy.load()).decision_for(reg.get("search_notes")) == "allow"
