"""Desktop notifications integration for SourceDock.

Allows sending safe desktop notifications using notify-send when available,
without requiring a separate background daemon process.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def send_desktop_notification(
    title: str,
    body: str,
    icon: str = "sourcedock",
    urgency: str = "normal",
    runner: Any = None,
) -> bool:
    """Send a desktop notification using notify-send.

    Returns True if notification command was executed, False otherwise.
    Strictly uses an argv list without shell expansion for safety.
    """
    if not title and not body:
        return False

    args = ["notify-send", "-a", "SourceDock", "-i", icon, "-u", urgency, title, body]

    if runner is not None and hasattr(runner, "command_exists") and hasattr(runner, "run"):
        if not runner.command_exists("notify-send"):
            return False
        try:
            res = runner.run(args, timeout=5)
            return getattr(res, "exit_code", 1) == 0
        except Exception:
            return False

    cmd = shutil.which("notify-send")
    if not cmd:
        return False
    try:
        res = subprocess.run(
            [cmd, "-a", "SourceDock", "-i", icon, "-u", urgency, title, body],
            check=False,
            timeout=5,
            capture_output=True,
        )
        return res.returncode == 0
    except Exception:
        return False

