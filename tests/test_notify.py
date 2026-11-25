import subprocess
import sys

import pytest

from rosie.notify import (
    TOAST_SCRIPT,
    DesktopNotifier,
    NotifyError,
    Router,
    idle_seconds,
)


class Recorder:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def __call__(self, title, text):
        if self.fail:
            raise NotifyError("down")
        self.sent.append((title, text))


def test_at_laptop_goes_to_desktop():
    desk, phone = Recorder(), Recorder()
    assert Router(desk, phone, idle=lambda: 30)("Rosie", "revise DBMS") == "desktop"
    assert desk.sent == [("Rosie", "revise DBMS")] and phone.sent == []


@pytest.mark.parametrize("idle", [600, None])
def test_away_or_unknown_goes_to_phone(idle):
    desk, phone = Recorder(), Recorder()
    assert Router(desk, phone, idle=lambda: idle)("Rosie", "gym") == "phone"
    assert desk.sent == []


def test_falls_back_when_preferred_channel_fails():
    desk, phone = Recorder(fail=True), Recorder()
    assert Router(desk, phone, idle=lambda: 1)("Rosie", "x") == "phone"
    desk, phone = Recorder(), Recorder(fail=True)
    assert Router(desk, phone, idle=lambda: 999)("Rosie", "x") == "desktop"


def test_missing_phone_uses_desktop_even_when_away():
    desk = Recorder()
    assert Router(desk, None, idle=lambda: 999)("Rosie", "x") == "desktop"


def test_all_channels_failing_raises():
    with pytest.raises(NotifyError, match="desktop: down; phone: down"):
        Router(Recorder(True), Recorder(True), idle=lambda: 1)("Rosie", "x")
    with pytest.raises(NotifyError, match="no channels"):
        Router(None, None)("Rosie", "x")


def test_toast_passes_text_through_env_not_script():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    evil = "'); Remove-Item C:\\ -Recurse; ('"
    DesktopNotifier(fake_run, platform="win32")("Rosie", evil)
    cmd, kwargs = calls[0]
    assert cmd[0] == "powershell.exe" and cmd[-1] == TOAST_SCRIPT
    assert evil not in " ".join(cmd)
    assert kwargs["env"]["ROSIE_TOAST_TEXT"] == evil
    assert "SecurityElement]::Escape" in TOAST_SCRIPT  # XML-escaped inside PowerShell


def test_toast_failure_becomes_notify_error():
    def broken(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    with pytest.raises(NotifyError, match="CalledProcessError"):
        DesktopNotifier(broken, platform="win32")("Rosie", "x")


def test_desktop_needs_windows():
    notifier = DesktopNotifier(platform="linux")
    assert not notifier.available
    with pytest.raises(NotifyError, match="Windows"):
        notifier("Rosie", "x")


def test_idle_seconds():
    assert idle_seconds("linux") is None
    if sys.platform.startswith("win"):  # real Win32 call on the Windows CI runner
        idle = idle_seconds()
        assert idle is None or idle >= 0
