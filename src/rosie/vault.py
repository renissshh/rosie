"""rosie-vault: Rosie's own Obsidian vault (D:\\Rosie\\rosie-vault), synced with git.

Layout (created on first run, existing files are never overwritten):

    daily/          morning briefs and nightly reviews, one note per day
    tasks/          tasks and reminders
    memory/         facts Rosie remembers about you
    study-log/      study sessions
    training-log/   workouts

Git gives two things for free: every change can be undone (so Rosie may delete her
own notes, see docs/decisions/0001) and the vault can be shared with an always-on
server later. Sync never raises: if the network is down the local commit is kept
and the next sync pushes it.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("rosie.vault")

FOLDERS: dict[str, str] = {
    "daily": "Morning briefs and nightly reviews, one note per day (YYYY-MM-DD.md).",
    "tasks": "Tasks and reminders Rosie manages for you.",
    "memory": "Facts Rosie remembers. Edit or delete any line; she follows what's here.",
    "study-log": "Study sessions: subject, duration, what was covered.",
    "training-log": "Workouts: exercises, sets, reps, weights.",
}

ROOT_README = """# rosie-vault

Rosie's own notes. Your personal vault is separate and Rosie only reads it.
Every change here is a git commit, so anything can be restored from history.
"""

# Rosie commits as herself, so history shows which changes she made.
GIT_IDENTITY = ("-c", "user.name=Rosie", "-c", "user.email=rosie@localhost")

Runner = Callable[..., subprocess.CompletedProcess]


def ensure_layout(root: Path) -> list[Path]:
    """Create the folders and their README notes. Returns the files it created."""
    created: list[Path] = []
    root.mkdir(parents=True, exist_ok=True)
    readmes = {root / "README.md": ROOT_README}
    for folder, purpose in FOLDERS.items():
        (root / folder).mkdir(exist_ok=True)
        readmes[root / folder / "README.md"] = f"# {folder}\n\n{purpose}\n"
    for path, text in readmes.items():
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            created.append(path)
    return created


@dataclass(frozen=True)
class SyncResult:
    committed: bool = False
    pushed: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class GitSync:
    def __init__(self, root: Path, run: Runner = subprocess.run, remote: str = "origin") -> None:
        self.root = root
        self.remote = remote
        self._run = run

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd: Sequence[str] = ["git", "-C", str(self.root), *GIT_IDENTITY, *args]
        return self._run(cmd, capture_output=True, text=True, check=check, timeout=60)

    def is_repo(self) -> bool:
        if not (self.root / ".git").exists():
            return False
        return self._git("rev-parse", "--is-inside-work-tree", check=False).returncode == 0

    def init(self) -> None:
        """Make the vault a git repo (branch main) if it isn't one yet."""
        if not self.is_repo():
            self._git("init", "-b", "main")

    def has_remote(self) -> bool:
        return self._git("remote", check=False).stdout.split().count(self.remote) > 0

    def commit_all(self, message: str) -> bool:
        self._git("add", "-A")
        if not self._git("status", "--porcelain").stdout.strip():
            return False
        self._git("commit", "-m", message)
        return True

    def sync(self, message: str = "rosie: update vault") -> SyncResult:
        """Commit local changes, then pull --rebase and push if a remote is set."""
        try:
            self.init()
            committed = self.commit_all(message)
        except (OSError, subprocess.SubprocessError) as exc:
            log.error("vault commit failed: %s", exc)
            return SyncResult(error=f"commit failed: {_why(exc)}")
        if not self.has_remote():
            return SyncResult(committed=committed)
        try:
            branch = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            remote_has_branch = self._git(
                "ls-remote", "--heads", self.remote, branch, check=False
            ).stdout.strip()
            if remote_has_branch:
                self._git("pull", "--rebase", "--autostash", self.remote, branch)
            self._git("push", "-u", self.remote, branch)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("vault sync failed, will retry next time: %s", exc)
            return SyncResult(committed=committed, error=f"sync failed: {_why(exc)}")
        return SyncResult(committed=committed, pushed=True)


def _why(exc: BaseException) -> str:
    """The most useful line of a git failure: the last line of stderr, else the error."""
    text = (getattr(exc, "stderr", None) or str(exc)).strip()
    return text.splitlines()[-1] if text else type(exc).__name__
