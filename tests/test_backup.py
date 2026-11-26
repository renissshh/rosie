import zipfile
from datetime import date

from rosie.backup import BACKUP_JOB, backup_vault, prune, schedule_backups
from rosie.scheduler import Scheduler


def make_vault(root):
    (root / "tasks").mkdir(parents=True)
    (root / "tasks" / "tasks.md").write_text("- [ ] revise DBMS ^a1\n", encoding="utf-8")
    (root / "README.md").write_text("# rosie-vault\n", encoding="utf-8")
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return root


def test_backup_zips_the_notes_but_not_git(tmp_path):
    vault = make_vault(tmp_path / "vault")
    zip_path = backup_vault(vault, tmp_path / "backups", date(2026, 11, 27))
    assert zip_path.name == "rosie-vault-2026-11-27.zip"
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ["README.md", "tasks/tasks.md"]
        assert archive.read("tasks/tasks.md").startswith(b"- [ ] revise DBMS")
    assert not list((tmp_path / "backups").glob("*.part"))


def test_same_day_backup_is_replaced(tmp_path):
    vault = make_vault(tmp_path / "vault")
    backup_vault(vault, tmp_path / "b", date(2026, 11, 27))
    (vault / "new.md").write_text("later\n", encoding="utf-8")
    zip_path = backup_vault(vault, tmp_path / "b", date(2026, 11, 27))
    with zipfile.ZipFile(zip_path) as archive:
        assert "new.md" in archive.namelist()
    assert len(list((tmp_path / "b").iterdir())) == 1


def test_only_the_newest_fourteen_are_kept(tmp_path):
    vault = make_vault(tmp_path / "vault")
    for day in range(1, 21):
        backup_vault(vault, tmp_path / "b", date(2026, 11, day))
    names = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert len(names) == 14
    assert names[0] == "rosie-vault-2026-11-07.zip"


def test_prune_ignores_other_files(tmp_path):
    (tmp_path / "notes.txt").write_text("mine", encoding="utf-8")
    (tmp_path / "rosie-vault-2026-01-01.zip").write_bytes(b"")
    assert [p.name for p in prune(tmp_path, keep=0)] == ["rosie-vault-2026-01-01.zip"]
    assert (tmp_path / "notes.txt").exists()


def test_backup_job_is_scheduled_once_and_runs(tmp_path):
    vault = make_vault(tmp_path / "vault")
    scheduler = Scheduler(tmp_path / "s.db", "Asia/Kolkata")
    for _ in range(2):  # every start calls it; still one job
        schedule_backups(scheduler, vault, tmp_path / "b", lambda: date(2026, 11, 27))
    jobs = [j for j in scheduler.jobs() if j.kind == BACKUP_JOB]
    assert [j.rule for j in jobs] == ["daily@03:00"]
    scheduler.handlers[BACKUP_JOB](jobs[0])
    assert (tmp_path / "b" / "rosie-vault-2026-11-27.zip").is_file()


def test_missing_vault_is_skipped(tmp_path):
    scheduler = Scheduler(tmp_path / "s.db", "Asia/Kolkata")
    schedule_backups(scheduler, tmp_path / "none", tmp_path / "b", lambda: date(2026, 11, 27))
    scheduler.handlers[BACKUP_JOB](None)
    assert not (tmp_path / "b").exists()
