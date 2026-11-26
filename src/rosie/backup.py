"""Daily backups of rosie-vault: one zip per day, the last 14 kept.

    D:\\Rosie\\backups\\rosie-vault-2026-11-27.zip

Git history already lets every change be undone, but a zip on disk also survives a
broken repository or a bad sync. Backups skip the .git folder (history lives on the
remote) and run from the scheduler at 03:00; a laptop that was asleep runs the missed
backup once when it wakes. Restoring is unzipping into an empty folder.
"""

from __future__ import annotations

import logging
import os
import zipfile
from datetime import date
from pathlib import Path

log = logging.getLogger("rosie.backup")

BACKUP_JOB = "vault_backup"
KEEP = 14
PREFIX = "rosie-vault-"


def backup_vault(vault: Path, backups: Path, today: date, keep: int = KEEP) -> Path:
    """Zip the vault (without .git) as rosie-vault-YYYY-MM-DD.zip, then prune old zips."""
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"{PREFIX}{today:%Y-%m-%d}.zip"
    partial = target.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(vault.rglob("*")):
            rel = path.relative_to(vault)
            if rel.parts[0] == ".git" or not path.is_file():
                continue
            archive.write(path, rel.as_posix())
    os.replace(partial, target)  # a crash mid-zip never leaves a half backup behind
    prune(backups, keep)
    return target


def prune(backups: Path, keep: int = KEEP) -> list[Path]:
    """Delete all but the newest `keep` backups (names sort by date). Returns the deleted."""
    zips = sorted(backups.glob(f"{PREFIX}*.zip"))
    old = zips[:-keep] if keep > 0 else zips
    for path in old:
        path.unlink(missing_ok=True)
    return old


def schedule_backups(scheduler, vault: Path, backups: Path, today, at: str = "03:00") -> None:
    def run(job=None) -> None:
        if vault.is_dir():
            log.info("vault backup: %s", backup_vault(vault, backups, today()))

    scheduler.on(BACKUP_JOB, run)
    scheduler.ensure_daily(BACKUP_JOB, at)
