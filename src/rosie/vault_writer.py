"""The only code in Rosie allowed to write notes, and it can only write in rosie-vault.

Every path goes through `VaultWriter.resolve`, which refuses:
- absolute paths, drive letters (C:...) and UNC paths (\\\\server\\share)
- anything that resolves outside the vault, including via `..` or a symlink
- the vault's .git folder
- anything that isn't a markdown note
- anything inside a forbidden folder (the user's own vault), as a second guard
  on top of the config check that keeps the two vaults apart

Writes are atomic (temp file + rename), so a crash never leaves half a note.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath


class VaultPathError(ValueError):
    """A write was refused because the path is not a note inside rosie-vault."""


class VaultWriter:
    def __init__(self, root: Path, forbidden: Iterable[Path] = ()) -> None:
        self.root = root.resolve()
        self.forbidden = [p.resolve() for p in forbidden]

    def resolve(self, rel: str) -> Path:
        text = rel.strip().replace("\\", "/")
        win = PureWindowsPath(rel)
        if not text or text.startswith("/") or win.drive or win.is_absolute():
            raise VaultPathError(f"'{rel}' must be a path inside rosie-vault")
        target = (self.root / text).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise VaultPathError(f"'{rel}' is outside rosie-vault")
        parts = target.relative_to(self.root).parts
        if parts and parts[0] == ".git":
            raise VaultPathError("rosie-vault's .git folder is off limits")
        if target.suffix.lower() != ".md":
            raise VaultPathError(f"'{rel}' is not a markdown note")
        for folder in self.forbidden:
            if target.is_relative_to(folder):
                raise VaultPathError(f"'{rel}' is inside your own vault, which is read only")
        return target

    def write(self, rel: str, text: str) -> Path:
        target = self.resolve(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return target

    def append(self, rel: str, text: str) -> Path:
        target = self.resolve(rel)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        return self.write(rel, existing + text)

    def read(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    def delete(self, rel: str) -> bool:
        """Delete one of Rosie's notes (recoverable from git history). False if missing."""
        target = self.resolve(rel)
        if not target.is_file():
            return False
        target.unlink()
        return True
