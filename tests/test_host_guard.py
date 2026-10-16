"""Prove command rejection happens before even a harmless sentinel can start."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.test_guard import TestCommandGuard, UnsafeTestCommand


class TestHostCommandGuard(unittest.TestCase):
    def test_rejects_transactions_privilege_shells_and_unknown_commands(self):
        guard = TestCommandGuard(Path(tempfile.gettempdir()))
        for command in (
            ["apt-get", "install", "test"], ["apt", "list"], ["dpkg", "-i", "test.deb"],
            ["dnf", "install", "test"], ["pacman", "-S", "test"], ["zypper", "install", "test"],
            ["flatpak", "install", "test"], ["snap", "refresh"], ["fwupdmgr", "update"],
            ["AppImageUpdate", "test.AppImage"], ["sudo", "true"], ["pkexec", "true"],
            ["flatpak-spawn", "--host", "true"], ["sh", "-c", "true"],
            ["dpkg-deb", "--extract", "test.deb", "/tmp/destination"], ["unknown-command"],
        ):
            with self.subTest(command=command), self.assertRaises(UnsafeTestCommand):
                guard.audit("subprocess.Popen", (command[0], command, None, None))

    def test_allows_only_required_read_operations_and_scoped_desktop_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = TestCommandGuard(root)
            for command in (
                [sys.executable, "-c", "print('fixture')"],
                ["dpkg-deb", "--field", "/tmp/test.deb", "Version"],
                ["dpkg", "--compare-versions", "1.0", "lt", "2.0"],
                ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                ["update-desktop-database", str(root / "applications")],
            ):
                guard.audit("subprocess.Popen", (command[0], command, None, None))
            for target in (root, Path.home(), root / ".." / "outside"):
                with self.subTest(target=target), self.assertRaises(UnsafeTestCommand):
                    guard.audit("subprocess.Popen", (
                        "update-desktop-database", ["update-desktop-database", str(target)], None, None,
                    ))

    def test_live_audit_hook_prevents_process_creation_and_shell_execution(self):
        # A fresh Python is necessary because audit hooks cannot be uninstalled.
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "started"
            sentinel = Path(directory) / "apt-get"
            sentinel.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            sentinel.chmod(0o755)
            script = """
import os, pathlib, subprocess, sys
from tools.test_guard import TestCommandGuard, UnsafeTestCommand
root = pathlib.Path(sys.argv[1])
sys.addaudithook(TestCommandGuard(root).audit)
for start in (
    lambda: subprocess.run([str(root / 'apt-get'), 'install', 'fixture']),
    lambda: subprocess.run('true', shell=True),
    lambda: os.system('true'),
    lambda: os.posix_spawn('/bin/true', ['/bin/true'], os.environ),
):
    try:
        start()
    except UnsafeTestCommand:
        continue
    raise AssertionError('command unexpectedly started')
"""
            result = subprocess.run(
                [sys.executable, "-c", script, directory], capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
