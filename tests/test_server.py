import threading

from rosie.__main__ import main, start_reminders
from rosie.brief import BRIEF_JOB
from rosie.config import RosieConfig
from rosie.review import REVIEW_JOB
from rosie.scheduler import Scheduler
from rosie.vault import SyncResult, sync_forever


def kinds(config):
    """Job kinds on this machine, without the vault backup (it runs everywhere)."""
    scheduler = Scheduler(config.data_dir / "index" / "scheduler.db", config.timezone)
    return sorted(j.kind for j in scheduler.jobs() if j.kind != "vault_backup")


def test_this_machine_owns_the_clock_by_default(tmp_path):
    config = RosieConfig(data_dir=tmp_path)
    _, stop = start_reminders(config, lambda title, text: None)
    stop.set()
    assert kinds(config) == sorted([BRIEF_JOB, REVIEW_JOB])


def test_with_a_server_the_laptop_drops_brief_and_review(tmp_path):
    start_reminders(RosieConfig(data_dir=tmp_path), lambda t, x: None)[1].set()
    config = RosieConfig(data_dir=tmp_path, clock="server")
    reminders, stop = start_reminders(config, lambda title, text: None)
    stop.set()
    assert kinds(config) == []  # jobs left over from earlier runs are gone too
    # ...but reminders set on this machine still work here
    reminders.remind("stretch", reminders.now())
    assert kinds(config) == ["reminder"]


def test_scheduler_drop_removes_one_kind():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        scheduler = Scheduler(Path(tmp) / "s.db", "Asia/Kolkata")
        scheduler.ensure_daily("a", "07:00")
        scheduler.ensure_daily("b", "08:00")
        assert scheduler.drop("a") == 1
        assert [j.kind for j in scheduler.jobs()] == ["b"]


class FakeSync:
    def __init__(self, stop_after):
        self.calls, self.stop_after, self.stop = 0, stop_after, threading.Event()

    def sync(self, message):
        self.calls += 1
        if self.calls == self.stop_after:
            self.stop.set()
        return SyncResult(error="offline" if self.calls == 1 else "")


def test_sync_forever_repeats_and_syncs_once_more_on_the_way_out():
    fake = FakeSync(stop_after=3)
    sync_forever(fake, fake.stop, every_s=0)
    assert fake.calls == 4  # 3 rounds, the last one set stop, then a final push


def test_rosie_server_without_telegram_explains(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROSIE_DATA_DIR", str(tmp_path / "Rosie"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert main(["server"]) == 1
    assert "TELEGRAM_BOT_TOKEN is not set" in capsys.readouterr().out


def test_config_knows_the_clock_owner():
    assert RosieConfig().clock == "here"
    assert RosieConfig(clock="server").vault_sync_minutes == 10
