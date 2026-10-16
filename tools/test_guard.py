"""Fail closed on unexpected external commands in the unit-test process.

This is an accident guard for trusted tests, not an OS sandbox for hostile code.
It deliberately does not reuse the application's transaction classification.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


class UnsafeTestCommand(RuntimeError):
    pass


class TestCommandGuard:
    def __init__(self, temporary_root: Path):
        self.temporary_root = temporary_root.resolve()
        self.python = Path(sys.executable).resolve()
        self.allowed = []
        self.blocked = []

    def _allowed(self, executable, arguments) -> bool:
        if not isinstance(arguments, (list, tuple)) or not arguments:
            return False
        command = [os.fsdecode(arg) for arg in arguments]
        executable = os.fsdecode(executable)
        resolved = Path(shutil.which(executable) or executable).resolve()
        name = resolved.name
        options = command[1:]
        if resolved == self.python:
            return True
        # Read metadata only; extract/build/control operations are not permitted.
        if name == "dpkg-deb":
            return (
                len(options) >= 2
                and options[0] in {"--field", "-f", "--info", "-I", "--contents", "-c"}
                and all(not arg.startswith("-") for arg in options[1:])
            )
        if name == "dpkg":
            return (
                len(options) == 4
                and options[0] == "--compare-versions"
                and options[2] in {"lt", "le", "eq", "ne", "ge", "gt"}
                and not options[1].startswith("-")
                and not options[3].startswith("-")
            )
        if name == "xprop":
            return options == ["-root", "_NET_SUPPORTING_WM_CHECK"]
        if name == "update-desktop-database" and len(options) == 1:
            target = Path(options[0]).resolve()
            return target != self.temporary_root and target.is_relative_to(self.temporary_root)
        return False

    def audit(self, event, arguments):
        if event == "subprocess.Popen":
            executable, command, _cwd, _env = arguments
            if self._allowed(executable, command):
                self.allowed.append(os.fsdecode(executable))
                return
            self.blocked.append(os.fsdecode(executable))
            raise UnsafeTestCommand(f"Host command blocked by test guard: {os.fsdecode(executable)}")
        if event in {"os.system", "os.exec", "os.posix_spawn", "os.posix_spawnp", "pty.spawn"}:
            self.blocked.append(event)
            raise UnsafeTestCommand(f"Host command blocked by test guard: {event}")
