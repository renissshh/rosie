"""Release helper: one version everywhere, and a checklist before tagging.

    python scripts/release.py versions        # where the version lives, and what it is
    python scripts/release.py bump 1.0.0      # write a new version into all of them
    python scripts/release.py check           # is this commit ready to tag?
    python scripts/release.py tag-merges      # tag sprint merges on main that have no tag

Rosie's version is written in seven files (Python package, orb page, Tauri shell and
their lock files). `bump` changes all of them at once so they can't drift apart;
`check` refuses a release when:

- the files disagree on the version;
- CHANGELOG.md has no section for it;
- a relative link in a markdown file points at a file that doesn't exist;
- docs/PLAN.md still has unchecked items (for the final 1.0 release only).

`tag-merges` is what CI runs on every push to main (.github/workflows/tag.yml): each
sprint merge commit, "Merge dev into main: v0.N ...", gets its tag `v0.N` if it has
none yet, so tags never depend on someone pushing them by hand.

Standard library only, so it runs before anything is installed. Dev tooling:
nothing in Rosie imports it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class VersionSpot:
    """One place the version is written: a file and a regex whose group 1 is the version."""

    path: str
    pattern: str

    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)


SPOTS = [
    VersionSpot("pyproject.toml", r'^version = "([^"]+)"'),
    VersionSpot("src/rosie/__init__.py", r'^__version__ = "([^"]+)"'),
    VersionSpot("ui/package.json", r'^  "version": "([^"]+)"'),
    # package-lock.json has the version twice: the top level and the root package "".
    VersionSpot("ui/package-lock.json", r'^  "name": "rosie-ui",\n  "version": "([^"]+)"'),
    VersionSpot(
        "ui/package-lock.json",
        r'^    "": \{\n      "name": "rosie-ui",\n      "version": "([^"]+)"',
    ),
    VersionSpot("ui/src-tauri/tauri.conf.json", r'^  "version": "([^"]+)"'),
    VersionSpot("ui/src-tauri/Cargo.toml", r'^version = "([^"]+)"'),
    VersionSpot("ui/src-tauri/Cargo.lock", r'^name = "rosie-ui"\nversion = "([^"]+)"'),
]


class ReleaseError(RuntimeError):
    pass


def read_versions(root: Path = ROOT) -> list[tuple[VersionSpot, str]]:
    found = []
    for spot in SPOTS:
        text = (root / spot.path).read_text(encoding="utf-8")
        match = spot.regex().search(text)
        if match is None:
            raise ReleaseError(f"{spot.path}: version not found (pattern {spot.pattern!r})")
        found.append((spot, match.group(1)))
    return found


def bump(new: str, root: Path = ROOT) -> list[str]:
    """Write `new` into every spot. Returns the files changed."""
    if not SEMVER.match(new):
        raise ReleaseError(f"{new!r} is not a version like 1.0.0")
    changed: list[str] = []
    for spot in SPOTS:
        path = root / spot.path
        # newline="" keeps the file's own line endings (CRLF on a Windows checkout)
        text = path.read_text(encoding="utf-8", newline="")
        flat = text.replace("\r\n", "\n")
        match = spot.regex().search(flat)
        if match is None:
            raise ReleaseError(f"{spot.path}: version not found")
        flat = flat[: match.start(1)] + new + flat[match.end(1) :]
        if "\r\n" in text:
            flat = flat.replace("\n", "\r\n")
        if flat != text:
            path.write_text(flat, encoding="utf-8", newline="")
            if spot.path not in changed:
                changed.append(spot.path)
    return changed


# -- checks ---------------------------------------------------------------------------

LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {"node_modules", ".git", "dist", "target", ".venv", ".pytest_cache"}


def markdown_files(root: Path = ROOT) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md") if not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1])
    )


def broken_links(root: Path = ROOT) -> list[str]:
    """Relative links and images in markdown that point at missing files.

    Web links (http, mailto) and same-page anchors (#...) are not checked; links
    inside code blocks are ignored, since they are examples, not links.
    """
    problems = []
    for md in markdown_files(root):
        text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.DOTALL)
        text = re.sub(r"`[^`\n]*`", "", text)
        for target in LINK.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (md.parent / path).exists():
                problems.append(f"{md.relative_to(root).as_posix()}: broken link {target}")
    return problems


def changelog_has(version: str, root: Path = ROOT) -> bool:
    """CHANGELOG.md sections are headed `## v1.0 ...` or `## v0.5 ...` (the tag name)."""
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return False
    tag = tag_for(version)
    return re.search(rf"^## {re.escape(tag)}\b", path.read_text(encoding="utf-8"), re.M) is not None


def tag_for(version: str) -> str:
    """1.0.0 -> v1.0, 0.5.0 -> v0.5, 1.0.1 -> v1.0.1 (the repo's tag names)."""
    major, minor, patch = version.split(".")
    return f"v{major}.{minor}" + (f".{patch}" if patch != "0" else "")


def unchecked_plan_items(root: Path = ROOT) -> list[str]:
    text = (root / "docs" / "PLAN.md").read_text(encoding="utf-8")
    return [line[len("- [ ] ") :] for line in text.splitlines() if line.startswith("- [ ] ")]


def check(root: Path = ROOT) -> list[str]:
    """Everything that stops this commit from being tagged. Empty = ready."""
    problems: list[str] = []
    found = read_versions(root)
    distinct = {v for _, v in found}
    if len(distinct) > 1:
        problems += [f"{spot.path}: version {v}" for spot, v in found]
        problems.insert(0, "versions disagree (fix with `python scripts/release.py bump X.Y.Z`):")
        return problems
    version = distinct.pop()
    if not changelog_has(version, root):
        problems.append(f"CHANGELOG.md has no `## {tag_for(version)}` section")
    problems += broken_links(root)
    if version.startswith("1.0."):
        problems += [f"docs/PLAN.md not done: {item}" for item in unchecked_plan_items(root)]
    return problems


# -- tags for sprint merges -----------------------------------------------------------

MERGE_SUBJECT = re.compile(r"^Merge dev into main: (v\d+\.\d+(?:\.\d+)?)\b")


def merge_tags(log: str) -> list[tuple[str, str, str]]:
    """(tag, commit, subject) for each sprint merge in `git log --format='%H %s'` output,
    oldest first. If two merges name the same tag, the first one keeps it."""
    found: dict[str, tuple[str, str, str]] = {}
    for line in reversed(log.strip().splitlines()):
        commit, _, subject = line.partition(" ")
        match = MERGE_SUBJECT.match(subject)
        if match and match.group(1) not in found:
            found[match.group(1)] = (match.group(1), commit, subject)
    return list(found.values())


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def tag_merges(root: Path = ROOT, ref: str = "HEAD", push: bool = False) -> list[str]:
    """Create the missing sprint-merge tags (annotated, message = the merge subject).
    With push=True they are pushed to origin too. Returns the tags created."""
    existing = set(git(root, "tag", "--list").split())
    created = []
    for tag, commit, subject in merge_tags(git(root, "log", "--merges", "--format=%H %s", ref)):
        if tag in existing:
            continue
        git(root, "tag", "-a", tag, commit, "-m", subject)
        created.append(tag)
    if push and created:
        git(root, "push", "origin", *[f"refs/tags/{tag}" for tag in created])
    return created


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("versions", help="show the version in every file")
    bump_cmd = sub.add_parser("bump", help="write a new version into every file")
    bump_cmd.add_argument("version")
    sub.add_parser("check", help="is this commit ready to tag?")
    tags_cmd = sub.add_parser("tag-merges", help="tag sprint merges that have no tag yet")
    tags_cmd.add_argument("--ref", default="HEAD", help="branch to look at (default HEAD)")
    tags_cmd.add_argument("--push", action="store_true", help="also push the new tags")
    args = parser.parse_args(argv)
    try:
        if args.command == "versions":
            for spot, version in read_versions(root):
                print(f"{version:10} {spot.path}")
            return 0
        if args.command == "bump":
            for path in bump(args.version, root):
                print(f"updated {path}")
            return 0
        if args.command == "tag-merges":
            created = tag_merges(root, args.ref, args.push)
            print("tagged " + ", ".join(created) if created else "every sprint merge has its tag")
            return 0
        problems = check(root)
    except ReleaseError as exc:
        print(exc)
        return 1
    if problems:
        print("Not ready to tag:")
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    version = read_versions(root)[0][1]
    print(f"Ready to tag {tag_for(version)} ({version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
