"""Bulk update input validation and persistent operation-detail preferences."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.distro import DistroInfo
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.errors import BackendError
from sourcedock.core.models import SOURCE_APT, SOURCE_FLATPAK, SOURCE_SNAP, UnifiedApplication
from sourcedock.preferences import AppPreferences, PreferencesStore


class TestBulkUpdateValidation(unittest.TestCase):
    def setUp(self):
        self.runner = MagicMock()
        self.runner.command_exists.return_value = True
        self.runner.run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.registry = ApplicationRegistry(
            distro_info=DistroInfo(native_manager=SOURCE_APT), runner=self.runner
        )

    def test_invalid_apt_names_never_reach_a_privileged_command(self):
        for name in ("", None, "--allow-unauthenticated", "editor;touch sentinel", "editor\nother", "../editor", "a=1"):
            with self.subTest(name=name):
                application = UnifiedApplication("apt:test", "Test", SOURCE_APT, package_name=name)
                with self.assertRaises(BackendError):
                    self.registry.update_all([application])
                self.runner.run_privileged.assert_not_called()

    def test_single_and_multiarch_apt_updates_preserve_exact_names(self):
        for names in (("editor",), ("libdemo:amd64", "libdemo:i386", "g++-12")):
            with self.subTest(names=names):
                self.runner.reset_mock()
                self.registry.update_packages(list(names))
                command = self.runner.run_privileged.call_args.args[0]
                self.assertEqual(command[command.index("--") + 1:], list(names))
                self.runner.run_privileged.assert_called_once()

    def test_mixed_sources_preserve_provider_commands(self):
        apt = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        for source, package in ((SOURCE_FLATPAK, "org.example.Editor"), (SOURCE_SNAP, "editor")):
            with self.subTest(source=source):
                self.runner.reset_mock()
                other = UnifiedApplication(
                    f"{source}:editor", "Editor", source, package_name=package,
                    install_path="/var/lib/flatpak/app/org.example.Editor",
                )
                self.registry.update_all([apt, other])
                commands = [call.args[0] for call in self.runner.run_privileged.call_args_list]
                self.assertEqual(sum(command[0] == "apt-get" for command in commands), 1)
                if source == SOURCE_SNAP:
                    self.assertIn(["snap", "refresh", package], commands)
                else:
                    self.runner.run.assert_called_once_with(
                        ["flatpak", "update", "--system", "-y", package], timeout=1800, check=False
                    )


class TestOperationDetailsPreferences(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "settings.json"
        for name, path in (
            ("CONFIG_PATH", self.path),
            ("LEGACY_CONFIG_PATH", Path(directory.name) / "legacy.json"),
            ("OLDER_CONFIG_PATH", Path(directory.name) / "older.json"),
        ):
            mocked = patch("sourcedock.preferences." + name, str(path))
            mocked.start()
            self.addCleanup(mocked.stop)
        self.store = PreferencesStore()

    def test_default_and_legacy_configuration_keep_details_closed(self):
        self.assertFalse(self.store.load().show_operation_details_by_default)
        self.path.write_text('{"language":"en","theme":"dark"}', encoding="utf-8")
        self.assertFalse(self.store.load().show_operation_details_by_default)

    def test_details_choice_survives_saving_and_reloading(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.store.save(replace(AppPreferences("en", "dark"), show_operation_details_by_default=value))
                self.assertIs(self.store.load().show_operation_details_by_default, value)

    def test_malformed_and_non_boolean_values_are_safe(self):
        for value in ("true", 1, None, [], {}):
            with self.subTest(value=value):
                self.path.write_text(json.dumps({"show_operation_details_by_default": value}), encoding="utf-8")
                self.assertFalse(self.store.load().show_operation_details_by_default)
        self.path.write_text("{invalid", encoding="utf-8")
        self.assertFalse(self.store.load().show_operation_details_by_default)
