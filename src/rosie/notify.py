"""Where a notification goes: the laptop screen or the phone.

    at the laptop (input in the last 5 minutes)  -> Windows toast
    away (idle, locked, or not on Windows)       -> Telegram
    the chosen channel fails                     -> try the other one

Desktop toasts use the built-in Windows PowerShell and WinRT, so no extra package.
The title and text are passed through environment variables, never pasted into the
script, so a reminder text can't inject PowerShell code. Idle time comes from the
Win32 GetLastInputInfo call via ctypes.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable

log = logging.getLogger("rosie.notify")

Notify = Callable[[str, str], None]
AWAY_AFTER_S = 300

# Windows PowerShell's app id lets the toast show without registering an app.
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
TOAST_SCRIPT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] | Out-Null;"
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
    "ContentType = WindowsRuntime] | Out-Null;"
    "$t = [Security.SecurityElement]::Escape($env:ROSIE_TOAST_TITLE);"
    "$b = [Security.SecurityElement]::Escape($env:ROSIE_TOAST_TEXT);"
    "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text>"
    '<text>$b</text></binding></visual></toast>");'
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    f"'{_APP_ID}').Show([Windows.UI.Notifications.ToastNotification]::new($x))"
)


class NotifyError(RuntimeError):
    """A notification channel failed."""


def idle_seconds(platform: str = sys.platform) -> float | None:
    """Seconds since the last keyboard/mouse input on Windows; None if unknown."""
    if not platform.startswith("win"):
        return None
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    windll = ctypes.windll  # type: ignore[attr-defined]
    if not windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    millis = (windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF  # tick count wraps
    return millis / 1000


class DesktopNotifier:
    def __init__(
        self,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        platform: str = sys.platform,
    ) -> None:
        self._run = run
        self.platform = platform

    @property
    def available(self) -> bool:
        return self.platform.startswith("win")

    def __call__(self, title: str, text: str) -> None:
        if not self.available:
            raise NotifyError("desktop notifications need Windows")
        env = {**os.environ, "ROSIE_TOAST_TITLE": title, "ROSIE_TOAST_TEXT": text}
        try:
            self._run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT],
                env=env,
                capture_output=True,
                timeout=15,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NotifyError(f"toast failed: {type(exc).__name__}") from exc


class Router:
    """Sends each notification to the right place, with the other as backup."""

    def __init__(
        self,
        desktop: Notify | None,
        phone: Notify | None,
        idle: Callable[[], float | None] = idle_seconds,
        away_after_s: float = AWAY_AFTER_S,
    ) -> None:
        self.desktop = desktop
        self.phone = phone
        self.idle = idle
        self.away_after_s = away_after_s

    def channels(self) -> list[tuple[str, Notify]]:
        """Preferred channel first."""
        idle = self.idle()
        at_laptop = idle is not None and idle < self.away_after_s
        order = [("desktop", self.desktop), ("phone", self.phone)]
        if not at_laptop:
            order.reverse()
        return [(name, fn) for name, fn in order if fn is not None]

    def __call__(self, title: str, text: str) -> str:
        """Deliver; returns the channel used. Raises only if every channel failed."""
        errors = []
        for name, send in self.channels():
            try:
                send(title, text)
                return name
            except Exception as exc:  # any channel failure -> try the next one
                log.warning("%s notification failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
        raise NotifyError("could not notify: " + ("; ".join(errors) or "no channels"))
