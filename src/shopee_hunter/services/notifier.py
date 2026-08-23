"""Desktop notifications, per OS, with a graceful no-op.

Deliberately not a dependency: macOS has ``osascript`` and Windows has PowerShell's toast
API, both already installed, and a notification is not worth a wheel that might not have a
build for one of our two platforms. If neither path works, the app logs and carries on — a
missed toast must never break a scan.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from collections.abc import Sequence

from ..core.logging import get_logger
from ..core.models import Deal

log = get_logger("services.notifier")

# Long titles get silently truncated by both OSes; keep the useful part first.
_MAX_BODY_CHARS = 180


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(text: str) -> str:
    return text.replace("'", "''")


class Notifier:
    """Sends one notification per new deal, at most a handful per scan."""

    # More than this and the OS coalesces them into an unreadable stack anyway.
    max_per_scan = 3

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    async def notify_deals(self, deals: Sequence[Deal]) -> int:
        """Announce up to ``max_per_scan`` deals; returns how many were sent."""
        if not self.enabled or not deals:
            return 0
        sent = 0
        for deal in list(deals)[: self.max_per_scan]:
            product = deal.product
            title = f"−{deal.true_discount_pct:.0f}% · {product.price}"
            body = f"{product.name[:_MAX_BODY_CHARS]}\nwas {deal.reference_price} · score {deal.score:.0f}"
            if await self.notify(title, body):
                sent += 1
        remaining = len(deals) - sent
        if remaining > 0:
            await self.notify(
                "Sale Hunter", f"+{remaining} more new deal(s) in the app"
            )
        return sent

    async def notify(self, title: str, body: str) -> bool:
        """Show one notification. Returns False when the platform path is unavailable."""
        try:
            if sys.platform == "darwin":
                return await self._notify_macos(title, body)
            if sys.platform == "win32":
                return await self._notify_windows(title, body)
        except (TimeoutError, OSError) as exc:
            log.debug("notification failed: %s", exc)
            return False
        log.debug("no notification backend for platform %s", sys.platform)
        return False

    async def _notify_macos(self, title: str, body: str) -> bool:
        if not shutil.which("osascript"):
            return False
        script = (
            f'display notification "{_escape_applescript(body)}" '
            f'with title "Sale Hunter" subtitle "{_escape_applescript(title)}"'
        )
        return await self._run("osascript", "-e", script)

    async def _notify_windows(self, title: str, body: str) -> bool:
        # WinRT toasts via PowerShell: no dependency, works on Windows 10+. Falls back to
        # nothing rather than a message box, which would steal focus mid-scan.
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{_escape_powershell(title)}')) > $null; "
            f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{_escape_powershell(body)}')) > $null; "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Sale Hunter')"
            ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        return await self._run("powershell", "-NoProfile", "-Command", script)

    async def _run(self, *command: str) -> bool:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            return False
        return process.returncode == 0
