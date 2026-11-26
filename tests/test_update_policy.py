"""Tests for per-source update schedule preferences and Snap auto-refresh controls."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.preferences import AppPreferences, PreferencesStore


class TestUpdatePolicyPreferences(unittest.TestCase):
    def test_load_migrates_legacy_check_updates_on_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "settings.json"
            cfg.write_text(json.dumps({"language": "tr", "theme": "dark", "check_updates_on_start": True}))
            with patch("sourcedock.preferences.CONFIG_PATH", str(cfg)):
                prefs = PreferencesStore().load()
            self.assertEqual(prefs.update_schedule_native, "on_start")
            self.assertEqual(prefs.update_schedule_flatpak, "on_start")
            self.assertEqual(prefs.update_schedule_snap, "on_start")

    def test_load_reads_per_source_schedules_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "settings.json"
            cfg.write_text(
                json.dumps(
                    {
                        "language": "en",
                        "theme": "light",
                        "update_schedule_native": "hourly",
                        "update_schedule_flatpak": "daily",
                        "update_schedule_snap": "invalid_value",
                    }
                )
            )
            with patch("sourcedock.preferences.CONFIG_PATH", str(cfg)):
                prefs = PreferencesStore().load()
            self.assertEqual(prefs.update_schedule_native, "hourly")
            self.assertEqual(prefs.update_schedule_flatpak, "daily")
            self.assertEqual(prefs.update_schedule_snap, "never")


class TestSnapAutoRefreshControl(unittest.TestCase):
    def _make_registry(self, runner):
        distro = SimpleNamespace(native_manager="apt", id="ubuntu", name="Ubuntu")
        return ApplicationRegistry(distro, runner)

    def test_get_snap_auto_refresh_paused_parses_hold(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = SimpleNamespace(
            returncode=0,
            stdout="timer: 00:00~24:00/4\nhold: forever\nlast: today at 10:34 +03\n",
        )
        reg = self._make_registry(runner)
        self.assertTrue(reg.get_snap_auto_refresh_paused())

        runner.run.return_value = SimpleNamespace(
            returncode=0,
            stdout="timer: 00:00~24:00/4\nlast: today at 10:34 +03\nnext: today at 16:58 +03\n",
        )
        self.assertFalse(reg.get_snap_auto_refresh_paused())

    def test_set_snap_auto_refresh_paused_runs_privileged_command(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        reg = self._make_registry(runner)

        reg.set_snap_auto_refresh_paused(True)
        runner.run_privileged.assert_called_with(["snap", "refresh", "--hold=forever"], timeout=30)

        reg.set_snap_auto_refresh_paused(False)
        runner.run_privileged.assert_called_with(["snap", "refresh", "--unhold"], timeout=30)


if __name__ == "__main__":
    unittest.main()
