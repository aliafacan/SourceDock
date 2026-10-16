"""Standalone actions must keep GTK responsive and preserve confirmation/auth."""

import threading
import time
import unittest
import importlib
import sys
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.models import SOURCE_APT, UnifiedApplication
from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog


class TestStandaloneActions(unittest.TestCase):
    def setUp(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")
        self.registry = MagicMock()
        self.app = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        for mocked in (
            patch("sourcedock.ui.components.app_details_dialog.load_metadata", return_value={}),
            patch("sourcedock.ui.components.app_details_dialog.Gtk.main_quit"),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.progress_patch = patch("sourcedock.ui.components.app_details_dialog.OperationProgressWindow")
        self.progress = self.progress_patch.start().return_value
        self.addCleanup(self.progress_patch.stop)
        self.history_patch = patch("sourcedock.ui.components.app_details_dialog.OperationHistory")
        self.history = self.history_patch.start().return_value
        self.addCleanup(self.history_patch.stop)
        self.dialog = InstalledAppDetailsDialog(self.app, self.registry, "en", standalone=True)
        self.addCleanup(self.dialog.destroy)

    def pump_until(self, condition):
        deadline = time.monotonic() + 3
        context = GLib.MainContext.default()
        while not condition() and time.monotonic() < deadline:
            context.iteration(False)
            time.sleep(0.001)
        self.assertTrue(condition())

    def test_update_runs_in_worker_and_gtk_can_tick_before_completion(self):
        release = threading.Event()
        started = threading.Event()
        threads = []

        def update(_application):
            threads.append(threading.get_ident())
            started.set()
            release.wait(3)

        self.registry.update.side_effect = update
        ticks = []
        try:
            self.dialog._on_update_clicked(None)
            self.assertTrue(started.wait(1))
            GLib.idle_add(lambda: ticks.append(True) and False)
            self.pump_until(lambda: bool(ticks))
            self.assertTrue(self.dialog._action_busy)
            self.assertFalse(self.dialog._action_bar.get_sensitive())
            self.dialog._on_update_clicked(None)
            self.registry.update.assert_called_once_with(self.app)
            self.assertNotEqual(threads, [threading.get_ident()])
        finally:
            release.set()
            self.dialog._action_thread.join(3)
        self.pump_until(lambda: not self.dialog._action_busy)
        self.assertTrue(self.dialog._destroyed)
        self.progress.finish.assert_called_once_with(True, "Update operation completed.")
        self.registry.runner.clear_sudo_password.assert_called()
        self.history.append.assert_called_once()

    def test_remove_keeps_purge_and_retries_auth_off_the_gtk_thread(self):
        self.registry.remove.side_effect = [AuthRequiredError("permission required"), None]
        with (
            patch("sourcedock.ui.components.app_details_dialog.Gtk.Dialog.run", return_value=Gtk.ResponseType.OK),
            patch("sourcedock.ui.components.app_details_dialog.Gtk.CheckButton.get_active", return_value=True),
            patch("sourcedock.ui.components.app_details_dialog.ask_sudo_password", return_value="test-password") as ask,
        ):
            self.dialog._on_remove_clicked(None)
            self.pump_until(lambda: not self.dialog._action_busy)
        self.assertEqual(self.registry.remove.call_count, 2)
        for call in self.registry.remove.call_args_list:
            self.assertEqual(call.kwargs, {"purge": True})
        ask.assert_called_once()
        self.registry.set_sudo_password.assert_called_once_with("test-password")
        self.assertEqual(self.registry.runner.clear_sudo_password.call_count, 2)
        self.history.append.assert_called_once()
        self.assertTrue(self.history.append.call_args.args[2])

    def test_cached_sudo_password_is_reused_without_prompting(self):
        self.dialog._cached_sudo_password = "cached-session-secret"
        self.registry.remove.side_effect = None
        with (
            patch("sourcedock.ui.components.app_details_dialog.Gtk.Dialog.run", return_value=Gtk.ResponseType.OK),
            patch("sourcedock.ui.components.app_details_dialog.Gtk.CheckButton.get_active", return_value=False),
            patch("sourcedock.ui.components.app_details_dialog.ask_sudo_password") as ask,
        ):
            self.dialog._on_remove_clicked(None)
            self.pump_until(lambda: not self.dialog._action_busy)
        ask.assert_not_called()
        self.registry.set_sudo_password.assert_called_with("cached-session-secret")
        self.registry.remove.assert_called_once()

    def test_cancelled_auth_does_not_retry_or_close_details(self):
        self.registry.update.side_effect = AuthRequiredError("permission required")
        with patch("sourcedock.ui.components.app_details_dialog.ask_sudo_password", return_value=None):
            self.dialog._on_update_clicked(None)
            self.pump_until(lambda: not self.dialog._action_busy)
        self.registry.update.assert_called_once()
        self.registry.set_sudo_password.assert_not_called()
        self.assertFalse(self.dialog._destroyed)
        self.assertTrue(self.dialog._action_bar.get_sensitive())
        self.assertFalse(self.progress.finish.call_args.args[0])

    def test_failure_keeps_details_open_and_records_failure(self):
        self.registry.update.side_effect = BackendError("offline")
        self.dialog._on_update_clicked(None)
        self.pump_until(lambda: not self.dialog._action_busy)
        self.assertFalse(self.dialog._destroyed)
        self.assertTrue(self.dialog._action_bar.get_sensitive())
        self.progress.finish.assert_called_once_with(False, "offline")
        self.assertFalse(self.history.append.call_args.args[2])

    def test_cancelled_removal_never_starts_a_worker(self):
        with patch("sourcedock.ui.components.app_details_dialog.Gtk.Dialog.run", return_value=Gtk.ResponseType.CANCEL):
            self.dialog._on_remove_clicked(None)
        self.registry.remove.assert_not_called()
        self.assertFalse(self.dialog._action_busy)
        self.history.append.assert_not_called()

    def test_destroy_during_worker_does_not_quit_until_operation_finishes(self):
        release = threading.Event()
        self.registry.update.side_effect = lambda _app: release.wait(3)
        with patch("sourcedock.ui.components.app_details_dialog.Gtk.main_quit") as quit_main:
            try:
                self.dialog._on_update_clicked(None)
                self.dialog.destroy()
                quit_main.assert_not_called()
            finally:
                release.set()
                self.dialog._action_thread.join(3)
            self.pump_until(lambda: not self.dialog._action_busy)
        self.progress.finish.assert_called_once()
        self.progress.connect.assert_called_once()


class TestUninstallEntryPoint(unittest.TestCase):
    def setUp(self):
        # Do not invoke the CLI's environment re-exec while importing its entry point.
        with patch.object(sys, "argv", ["-c"]):
            self.entry = importlib.import_module("main")

    def invoke(self, name, application):
        registry = MagicMock()
        registry.find_application.return_value = application
        registry.native_provider.source = SOURCE_APT
        from sourcedock.preferences import AppPreferences

        with (
            patch.object(sys, "argv", ["sourcedock", "--uninstall", name]),
            patch.object(self.entry.os, "geteuid", return_value=1000),
            patch.object(self.entry, "PreferencesStore") as preferences,
            patch("sourcedock.backend.manager.ApplicationRegistry", return_value=registry),
            patch("sourcedock.ui.components.app_details_dialog.InstalledAppDetailsDialog") as details,
            patch.object(self.entry.GLib, "idle_add") as queue,
            patch.object(self.entry.Gtk, "main"),
            self.assertRaises(SystemExit) as result,
        ):
            preferences.return_value.load.return_value = AppPreferences("en", "light")
            self.entry.main()
        self.assertEqual(result.exception.code, 0)
        queue.assert_called_once_with(details.return_value._on_remove_clicked, None)
        registry.runner.run_privileged.assert_not_called()
        registry.remove.assert_not_called()
        return registry, details.call_args.kwargs

    def test_desktop_uninstall_uses_shared_confirmation_and_async_details(self):
        app = UnifiedApplication("apt:systemd", "systemd", SOURCE_APT, package_name="systemd")
        _registry, arguments = self.invoke("systemd.desktop", app)
        self.assertIs(arguments["application"], app)
        self.assertTrue(arguments["standalone"])
        self.assertIsNone(arguments["removal_operation"])

    def test_legacy_self_uninstall_retains_manual_installation_script(self):
        registry, arguments = self.invoke("voltapp.desktop", None)
        self.assertEqual(arguments["application"].package_name, "sourcedock")
        arguments["removal_operation"]()
        command = registry.runner.run_privileged.call_args.args[0]
        self.assertEqual(command[0], "bash")
        self.assertTrue(command[1].endswith("/uninstall.sh"))
        registry.remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
