"""scripts/release.py: one version everywhere, and the checklist before tagging."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(_spec)
sys.modules["release"] = release  # dataclasses look their module up here
_spec.loader.exec_module(release)


def copy_repo_bits(tmp_path: Path) -> Path:
    """The version files, PLAN and CHANGELOG of this repo, in a temp folder."""
    for rel in {spot.path for spot in release.SPOTS} | {"docs/PLAN.md", "CHANGELOG.md"}:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


# -- guards on the real repo (these run on every commit) ------------------------------


def test_every_file_has_the_same_version() -> None:
    found = release.read_versions(ROOT)
    assert len(found) == len(release.SPOTS)
    assert len({v for _, v in found}) == 1, found


def test_package_version_matches_the_files() -> None:
    import rosie

    assert release.read_versions(ROOT)[0][1] == rosie.__version__


def test_no_broken_links_in_the_docs() -> None:
    assert release.broken_links(ROOT) == []


def test_changelog_has_a_section_for_every_tag_so_far() -> None:
    for version in ["0.1.0", "0.2.0", "0.3.0", "0.4.0", "0.5.0"]:
        assert release.changelog_has(version, ROOT), version


# -- bump -----------------------------------------------------------------------------


def test_bump_writes_every_spot(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    changed = release.bump("1.0.0", root)
    assert len(changed) == 7  # files; package-lock.json holds two spots
    assert {v for _, v in release.read_versions(root)} == {"1.0.0"}


def test_bump_leaves_other_versions_alone(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    lock = root / "ui" / "src-tauri" / "Cargo.lock"
    before = lock.read_text(encoding="utf-8")
    release.bump("1.0.0", root)
    after = lock.read_text(encoding="utf-8")
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert diff == [('version = "0.5.0"', 'version = "1.0.0"')]


def test_bump_keeps_windows_line_endings(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    path = root / "pyproject.toml"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    release.bump("1.0.0", root)
    data = path.read_bytes()
    assert b'version = "1.0.0"\r\n' in data
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_bump_refuses_a_bad_version(tmp_path: Path) -> None:
    with pytest.raises(release.ReleaseError):
        release.bump("1.0", copy_repo_bits(tmp_path))


# -- check ----------------------------------------------------------------------------


def test_tag_names() -> None:
    assert release.tag_for("1.0.0") == "v1.0"
    assert release.tag_for("0.5.0") == "v0.5"
    assert release.tag_for("1.0.1") == "v1.0.1"


def test_check_catches_drifted_versions(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    init = root / "src" / "rosie" / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace("0.5.0", "0.6.0"), encoding="utf-8")
    problems = release.check(root)
    assert problems[0].startswith("versions disagree")
    assert "src/rosie/__init__.py: version 0.6.0" in problems


def test_check_wants_a_changelog_section(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    release.bump("0.9.0", root)
    assert "CHANGELOG.md has no `## v0.9` section" in release.check(root)


def test_v1_needs_the_whole_plan_done(tmp_path: Path) -> None:
    root = copy_repo_bits(tmp_path)
    (root / "docs" / "PLAN.md").write_text("- [x] one\n- [ ] two\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("## v1.0 done\n", encoding="utf-8")
    release.bump("1.0.0", root)
    assert release.check(root) == ["docs/PLAN.md not done: two"]
    (root / "docs" / "PLAN.md").write_text("- [x] one\n- [x] two\n", encoding="utf-8")
    assert release.check(root) == []


def test_broken_links_finds_missing_files_but_not_web_links_or_code(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "real.md").write_text("# real\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "[ok](docs/real.md) [anchor](docs/real.md#real) [top](#x)",
                "[web](https://example.com) ![pic](docs/missing.png)",
                "`[not a link](nope.md)`",
                "```",
                "[example](also-nope.md)",
                "```",
                '[gone](docs/gone.md "title")',
            ]
        ),
        encoding="utf-8",
    )
    assert release.broken_links(tmp_path) == [
        "README.md: broken link docs/missing.png",
        "README.md: broken link docs/gone.md",
    ]


def test_main_check_reports_and_exits_1(tmp_path: Path, capsys) -> None:
    root = copy_repo_bits(tmp_path)
    assert release.main(["bump", "0.9.0"], root) == 0
    assert release.main(["check"], root) == 1
    out = capsys.readouterr().out
    assert "Not ready to tag" in out
    assert "no `## v0.9` section" in out


def test_main_check_says_ready(tmp_path: Path, capsys) -> None:
    root = copy_repo_bits(tmp_path)
    (root / "CHANGELOG.md").write_text("## v0.5 opens at login\n", encoding="utf-8")
    assert release.main(["check"], root) == 0
    assert "Ready to tag v0.5 (0.5.0)." in capsys.readouterr().out
