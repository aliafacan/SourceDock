"""Unit tests for v2.0.0 features: disk cleanup and XDG autostart management."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sourcedock.backend.autostart import (
    create_user_autostart_entry,
    is_autostart_enabled,
    list_autostart_entries,
    remove_user_autostart_entry,
    set_autostart_enabled,
)
from sourcedock.backend.disk_cleanup import (
    DiskCleanupPlan,
    SnapOldRevision,
    apply_disk_cleanup,
    format_bytes,
    plan_disk_cleanup,
)
from sourcedock.core.models import SOURCE_APT, UnifiedApplication


class TestDiskCleanup(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), "0 MB")
        self.assertEqual(format_bytes(10 * 1024 * 1024), "10.0 MB")
        self.assertEqual(format_bytes(2 * 1024 * 1024 * 1024), "2.00 GB")

    def test_plan_and_apply_disk_cleanup(self):
        runner = MagicMock()
        runner.command_exists.side_effect = lambda cmd: cmd in {"apt-get", "snap"}

        def fake_run(cmd, **kwargs):
            if cmd == ["apt-get", "-s", "autoremove"]:
                return SimpleNamespace(returncode=0, stdout="Remv old-lib [1.0]\nRemv unused-pkg [2.0]\n")
            if cmd == ["snap", "list", "--all"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout=(
                        "Name  Version  Rev  Tracking  Publisher  Notes\n"
                        "firefox  130  100  latest/stable  mozilla  -\n"
                        "firefox  129  99   latest/stable  mozilla  disabled\n"
                    ),
                )
            return SimpleNamespace(returncode=1, stdout="")

        runner.run.side_effect = fake_run
        plan = plan_disk_cleanup(runner, native_manager="apt")
        self.assertEqual(plan.apt_autoremove_packages, ["old-lib", "unused-pkg"])
        self.assertEqual(len(plan.snap_old_revisions), 1)
        self.assertEqual(plan.snap_old_revisions[0].name, "firefox")
        self.assertEqual(plan.snap_old_revisions[0].revision, "99")

        apply_disk_cleanup(
            runner,
            plan,
            clean_apt_autoremove=True,
            clean_snap_old=True,
        )
        runner.run_privileged.assert_any_call(
            ["apt-get", "-o", "DPkg::Lock::Timeout=0", "autoremove", "-y"], timeout=600
        )
        runner.run_privileged.assert_any_call(
            ["snap", "remove", "firefox", "--revision=99"], timeout=120
        )


class TestAutostartManagement(unittest.TestCase):
    def test_autostart_enable_and_disable_via_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                app = UnifiedApplication(
                    id="apt:myapp",
                    name="My App",
                    source=SOURCE_APT,
                    package_name="myapp",
                    executable="/usr/bin/myapp",
                )
                self.assertFalse(is_autostart_enabled(app))
                set_autostart_enabled(app, True)
                self.assertTrue(is_autostart_enabled(app))
                desktop_path = Path(tmp) / "autostart" / "sourcedock-myapp.desktop"
                self.assertTrue(desktop_path.is_file())
                set_autostart_enabled(app, False)
                self.assertFalse(is_autostart_enabled(app))
                self.assertFalse(desktop_path.exists())

    def test_create_custom_autostart_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                bg = create_user_autostart_entry("Sync Daemon", "/usr/bin/rclone mount", mode="background")
                term = create_user_autostart_entry("Monitor", "htop", mode="terminal")
                self.assertIn("sh -c '/usr/bin/rclone mount >/dev/null 2>&1 &'", bg.read_text(encoding="utf-8"))
                self.assertIn("Terminal=true", term.read_text(encoding="utf-8"))
                user_entries = [e for e in list_autostart_entries() if not e.is_system]
                self.assertEqual(len(user_entries), 2)

    def test_remove_broken_symlink_autostart_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                auto_dir = Path(tmp) / "autostart"
                auto_dir.mkdir(parents=True, exist_ok=True)
                broken = auto_dir / "windscribe.desktop"
                broken.symlink_to("/nonexistent/windscribe.desktop")
                entries = [e for e in list_autostart_entries() if e.filename == "windscribe.desktop"]
                self.assertEqual(len(entries), 1)
                remove_user_autostart_entry(entries[0])
                self.assertFalse(broken.exists() or broken.is_symlink())


if __name__ == "__main__":
    unittest.main()
