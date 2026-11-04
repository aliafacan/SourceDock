"""Operation feedback and read-only inventory queries without host mutations."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.apt import AptProvider
from sourcedock.backend.dnf import DnfProvider
from sourcedock.backend.pacman import PacmanProvider
from sourcedock.backend.zypper import ZypperProvider
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.models import SOURCE_PORTABLE, UnifiedApplication
from sourcedock.core.errors import BackendError
from sourcedock.core.runner import CommandRunner


class TestOperationFeedback(unittest.TestCase):
    def test_internal_checks_can_capture_diagnostics_without_streaming_them(self):
        runner = CommandRunner()
        lines = []
        runner.set_output_callback(lines.append)
        result = runner.run([sys.executable, "-c", "print('sudo: a password is required')"], emit_output=False)
        self.assertIn("password is required", result.stdout)
        self.assertEqual(lines, [])

    def test_auth_probe_and_validation_are_silent_but_failures_remain_checked(self):
        runner = CommandRunner()
        runner.set_sudo_password("fixture-password")
        lines = []
        runner.set_output_callback(lines.append)
        with (
            patch("sourcedock.core.runner.shutil.which", return_value="/usr/bin/sudo"),
            patch.object(runner, "run", side_effect=[
                subprocess.CompletedProcess([], 1, "", "sudo: a password is required"),
                subprocess.CompletedProcess([], 0, "", ""),
            ]) as run,
            patch.object(runner, "_execute_privileged_command", return_value=subprocess.CompletedProcess([], 0, "", "")),
        ):
            runner.run_privileged(["snap", "refresh", "example"])
        self.assertTrue(all(call.kwargs["emit_output"] is False for call in run.call_args_list))
        self.assertEqual(lines, ["SOURCEDOCK_PHASE authorizing"])
        self.assertIsNone(runner._sudo_password)

    def test_all_native_inventories_can_skip_update_queries(self):
        for provider_class, output, method in (
            (AptProvider, "editor\t1\t10\tEditor\tinstalled\n", "_upgradable_packages_with_versions"),
            (DnfProvider, "editor\t1\t1024\tEditor\n", "_upgradable_packages"),
            (PacmanProvider, "editor 1\n", "_upgradable_packages"),
            (ZypperProvider, "editor\t1\t1024\tEditor\n", "_upgradable_packages"),
        ):
            with self.subTest(provider=provider_class.__name__):
                runner = MagicMock()
                runner.command_exists.return_value = True
                runner.run.return_value = subprocess.CompletedProcess([], 0, output, "")
                provider = provider_class(runner, MagicMock())
                with patch.object(provider, method) as updates:
                    packages = provider.list_all_packages(include_updates=False)
                updates.assert_not_called()
                self.assertEqual([package.name for package in packages], ["editor"])

    def test_failed_native_metadata_reads_never_look_like_empty_inventories(self):
        for provider_class in (AptProvider, DnfProvider, PacmanProvider, ZypperProvider):
            with self.subTest(provider=provider_class.__name__):
                runner = MagicMock()
                runner.command_exists.return_value = True
                runner.run.return_value = subprocess.CompletedProcess([], 1, "", "inventory failed")
                with self.assertRaises(BackendError):
                    provider_class(runner, MagicMock()).list_all_packages(include_updates=False)

    def test_portable_launch_uses_its_desktop_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            desktop = Path(directory) / "portable.desktop"
            desktop.write_text("[Desktop Entry]\nType=Application\n", encoding="utf-8")
            registry = ApplicationRegistry.__new__(ApplicationRegistry)
            registry.runner = MagicMock()
            registry.runner.command_exists.return_value = True
            app = UnifiedApplication("portable:editor", "Editor", SOURCE_PORTABLE,
                                     desktop_file=str(desktop), executable="/unused/binary")
            registry.launch(app)
            registry.runner.spawn.assert_called_once_with(["gio", "launch", str(desktop)], desktop_file=str(desktop))

    def test_desktop_launch_does_not_inherit_the_parent_app_identity(self):
        runner = CommandRunner()
        runner.host_bridge_available = False
        with patch.dict(os.environ, {
            "BAMF_DESKTOP_FILE_HINT": "/parent.desktop", "GIO_LAUNCHED_DESKTOP_FILE": "/parent.desktop",
            "GIO_LAUNCHED_DESKTOP_FILE_PID": "123", "GTK_PATH": "/snap/editor/gtk",
        }), patch("sourcedock.core.runner.subprocess.Popen") as spawn:
            runner.spawn(["gio", "launch", "/portable.desktop"], desktop_file="/portable.desktop")
        environment = spawn.call_args.kwargs["env"]
        self.assertEqual(environment["BAMF_DESKTOP_FILE_HINT"], "/portable.desktop")
        self.assertEqual(environment["GIO_LAUNCHED_DESKTOP_FILE"], "/portable.desktop")
        self.assertNotIn("GTK_PATH", environment)
