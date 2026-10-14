#!/usr/bin/env python3
"""Donanım yazılımı (Firmware) ve Flatpak/Snap sistem çalışma ortamı güncellemeleri testleri."""

import json
import unittest
from unittest.mock import MagicMock

import subprocess

from sourcedock.core.models import (
    SOURCE_FIRMWARE,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.firmware import FirmwareProvider
from sourcedock.backend.flatpak import FlatpakProvider
from sourcedock.backend.snap import SnapProvider
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.scanner import DesktopEntryScanner


class TestFirmwareProvider(unittest.TestCase):
    """FirmwareProvider birim testleri."""

    def test_firmware_provider_not_available(self):
        runner = MagicMock(spec=CommandRunner)
        runner.command_exists.return_value = False
        provider = FirmwareProvider(runner)
        self.assertFalse(provider.is_available())
        self.assertEqual(provider.list_applications(), [])

    def test_firmware_provider_parse_updates(self):
        runner = MagicMock(spec=CommandRunner)
        runner.command_exists.return_value = True

        fake_json = {
            "Devices": [
                {
                    "DeviceId": "test-uefi-dbx-id",
                    "Name": "UEFI dbx",
                    "Summary": "Secure Boot dbx",
                    "Version": "371",
                    "Releases": [{"Version": "426", "Summary": "Updated dbx entries"}],
                }
            ]
        }
        runner.run.return_value = subprocess.CompletedProcess(
            args=["fwupdmgr"],
            returncode=0,
            stdout=json.dumps(fake_json),
            stderr="",
        )

        provider = FirmwareProvider(runner)
        apps = provider.list_applications()

        self.assertEqual(len(apps), 1)
        app = apps[0]
        self.assertEqual(app.source, SOURCE_FIRMWARE)
        self.assertEqual(app.id, f"{SOURCE_FIRMWARE}:test-uefi-dbx-id")
        self.assertEqual(app.name, "UEFI dbx (Secure Boot dbx)")
        self.assertEqual(app.version, "371")
        self.assertTrue(app.update_available)
        self.assertEqual(app.update_note, "-> 426")
        self.assertEqual(app.package_name, "test-uefi-dbx-id")

    def test_firmware_commands(self):
        runner = MagicMock(spec=CommandRunner)
        provider = FirmwareProvider(runner)

        self.assertEqual(provider.update_command("device-123"), ["fwupdmgr", "update", "-y", "device-123"])
        self.assertEqual(provider.update_command(), ["fwupdmgr", "update", "-y"])
        self.assertEqual(provider.update_all_command(), ["fwupdmgr", "update", "-y"])
        self.assertEqual(provider.refresh_cache_command(), ["fwupdmgr", "refresh", "--no-authenticate"])


class TestFlatpakAndSnapRuntimes(unittest.TestCase):
    """Flatpak ve Snap çalışma ortamı güncellemeleri testleri."""

    def test_flatpak_runtime_updates_included(self):
        runner = MagicMock(spec=CommandRunner)
        scanner = MagicMock(spec=DesktopEntryScanner)
        scanner.list_entries.return_value = []
        runner.command_exists.return_value = True

        # flatpak list --app
        app_list_res = subprocess.CompletedProcess(
            args=["flatpak"],
            returncode=0,
            stdout="org.example.App\tExample App\t1.0.0\tflathub\tsystem\t100 MB\n",
            stderr="",
        )
        # flatpak remote-ls --updates --columns=application
        updates_res = subprocess.CompletedProcess(
            args=["flatpak"],
            returncode=0,
            stdout="org.example.App\norg.freedesktop.Platform.GL.default\n",
            stderr="",
        )
        # flatpak list --runtime
        runtime_res = subprocess.CompletedProcess(
            args=["flatpak"],
            returncode=0,
            stdout="org.freedesktop.Platform.GL.default\tMesa\t24.08\tflathub\tsystem\t250 MB\tMesa 3D Graphics\n",
            stderr="",
        )

        def run_side_effect(cmd, **kwargs):
            if "--app" in cmd:
                return app_list_res
            if "--updates" in cmd:
                return updates_res
            if "--runtime" in cmd:
                return runtime_res
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        runner.run.side_effect = run_side_effect

        provider = FlatpakProvider(runner, scanner)
        apps = provider.list_applications()

        pkg_names = [a.package_name for a in apps]
        self.assertIn("org.example.App", pkg_names)
        self.assertIn("org.freedesktop.Platform.GL.default", pkg_names)

        runtime_app = next(a for a in apps if a.package_name == "org.freedesktop.Platform.GL.default")
        self.assertTrue(runtime_app.update_available)
        self.assertEqual(runtime_app.category, "System")
        self.assertIn("Mesa", runtime_app.name)

    def test_snap_runtime_updates_included(self):
        runner = MagicMock(spec=CommandRunner)
        scanner = MagicMock(spec=DesktopEntryScanner)
        scanner.list_entries.return_value = []
        runner.command_exists.return_value = True

        # snap list
        snap_list_res = subprocess.CompletedProcess(
            args=["snap"],
            returncode=0,
            stdout="Name Version Rev Tracking Publisher Notes\ngnome-46-2404 46 123 latest/stable canonical* base\n",
            stderr="",
        )
        # snap refresh --list
        snap_refresh_res = subprocess.CompletedProcess(
            args=["snap"],
            returncode=0,
            stdout="Name Version Rev Publisher Notes\ngnome-46-2404 46-new 125 canonical* -\n",
            stderr="",
        )

        def run_side_effect(cmd, **kwargs):
            if cmd == ["snap", "list"]:
                return snap_list_res
            if cmd == ["snap", "refresh", "--list"]:
                return snap_refresh_res
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        runner.run.side_effect = run_side_effect

        provider = SnapProvider(runner, scanner)
        apps = provider.list_applications()

        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].package_name, "gnome-46-2404")
        self.assertTrue(apps[0].update_available)
        self.assertEqual(apps[0].source, SOURCE_SNAP)


class TestRegistryFirmwareDispatch(unittest.TestCase):
    """ApplicationRegistry üzerinde Firmware güncelleme yönlendirmeleri."""

    def test_registry_update_firmware(self):
        runner = MagicMock(spec=CommandRunner)
        runner.command_exists.return_value = True
        registry = ApplicationRegistry(runner=runner)

        app = UnifiedApplication(
            id=f"{SOURCE_FIRMWARE}:fw-dev-1",
            name="UEFI dbx",
            source=SOURCE_FIRMWARE,
            package_name="fw-dev-1",
            update_available=True,
        )

        registry.update(app)
        runner.run.assert_called_with(["fwupdmgr", "update", "-y", "fw-dev-1"], timeout=1800, check=True)

    def test_registry_update_all_firmware(self):
        runner = MagicMock(spec=CommandRunner)
        runner.command_exists.return_value = True
        registry = ApplicationRegistry(runner=runner)

        apps = [
            UnifiedApplication(
                id=f"{SOURCE_FIRMWARE}:fw-dev-1",
                name="UEFI dbx",
                source=SOURCE_FIRMWARE,
                package_name="fw-dev-1",
                update_available=True,
            )
        ]

        registry.update_all(apps)
        runner.run.assert_any_call(["fwupdmgr", "update", "-y"], timeout=3600, check=False)


if __name__ == "__main__":
    unittest.main()
