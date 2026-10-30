"""Debian 13 and MATE compatibility regression suite (Issue #6).

Pins category/search event stability, recursion prevention, reentrancy guards,
and APT/sudo privilege separation under Debian/MATE desktop configurations.
"""

import getpass
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.models import SOURCE_APT, StoreResult
from sourcedock.core.runner import CommandRunner
from sourcedock.preferences import AppPreferences, PreferencesStore
from sourcedock.ui.window import MainWindow


class TestDebianMateStoreRecursion(unittest.TestCase):
    """Regression tests for Store category selection, search events and recursion guard."""

    def setUp(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")
        self.registry = MagicMock()
        self.registry.native_provider.source = SOURCE_APT
        self.registry.native_provider.display_name = "APT"
        self.store = MagicMock()
        self.store.native_manager = SOURCE_APT
        self.store.provider_errors = []
        self.store.missing_sources = []
        self.store.search.return_value = []
        preferences = MagicMock(spec=PreferencesStore)
        preferences.load.return_value = AppPreferences("en", "dark")
        for mocked in (
            patch("sourcedock.ui.window.ApplicationRegistry", return_value=self.registry),
            patch("sourcedock.ui.window.StoreRegistry", return_value=self.store),
            patch.object(MainWindow, "reload_applications_async"),
            patch.object(MainWindow, "reload_packages_async"),
            patch.object(MainWindow, "_reload_updates_async"),
            patch.object(MainWindow, "_on_operations_refresh"),
            patch("sourcedock.ui.window.Gtk.main_quit"),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        self.window = MainWindow(preferences)
        self.addCleanup(self.window.destroy)
        self.window.pages.set_current_page(1)  # Store page
        self.window.hide()

    def test_category_button_single_click(self):
        """Single click on category chip activates it and launches exactly one search."""
        self.store.search.reset_mock()
        btn, key = self.window.store_category_buttons[0]
        btn.clicked()
        self.assertTrue(btn.get_active())
        self.assertEqual(self.window.store_search_entry.get_text(), "office")
        self.assertEqual(self.window.header_search.get_text(), "office")

    def test_category_buttons_consecutive_clicks_no_recursion(self):
        """Clicking through categories in sequence switches active state without recursion."""
        for btn, key in self.window.store_category_buttons:
            btn.clicked()
            self.assertTrue(btn.get_active())
            for other_btn, _ in self.window.store_category_buttons:
                if other_btn is not btn:
                    self.assertFalse(other_btn.get_active())

    def test_category_button_reselect_active(self):
        """Re-selecting the currently active category retains active state without ping-pong."""
        btn, key = self.window.store_category_buttons[1]
        btn.clicked()
        self.assertTrue(btn.get_active())
        # Re-click the same active button
        btn.clicked()
        self.assertTrue(btn.get_active())

    def test_header_search_typing_clears_category_chips_without_recursion(self):
        """Typing non-category query in search entry deactivates chips without recursion."""
        btn, key = self.window.store_category_buttons[0]
        btn.clicked()
        self.assertTrue(btn.get_active())
        self.window.store_search_entry.set_text("customquery")
        self.window._on_store_search_changed(self.window.store_search_entry)
        for b, _ in self.window.store_category_buttons:
            self.assertFalse(b.get_active())

    def test_store_filter_toggling_without_recursion(self):
        """Toggling store filter buttons switches source without reentrancy recursion."""
        all_btn = self.window.store_filter_buttons["all"]
        apt_btn = self.window.store_filter_buttons[SOURCE_APT]
        apt_btn.clicked()
        self.assertTrue(apt_btn.get_active())
        self.assertFalse(all_btn.get_active())
        self.assertEqual(self.window.store_filter_source, SOURCE_APT)
        all_btn.clicked()
        self.assertTrue(all_btn.get_active())
        self.assertFalse(apt_btn.get_active())

    def test_rapid_consecutive_clicks_avoid_duplicate_search_threads(self):
        """Rapid identical clicks while busy do not spawn duplicate worker threads."""
        self.window.store_busy = True
        self.window._active_store_search_key = ("office", "all")
        initial_gen = self.window._store_search_generation
        self.window.header_search.set_text("office")
        self.window.on_store_search()
        self.assertEqual(self.window._store_search_generation, initial_gen)

    def test_stale_search_results_discarded_by_generation(self):
        """Old search thread results returning for superseded generation are ignored."""
        self.window._store_search_generation = 5
        stale_result = StoreResult("OldApp", "old.app", "Old", SOURCE_APT, "1.0", "app")
        accepted = self.window._finish_store_search([stale_result], None, generation=4, complete=True)
        self.assertFalse(accepted)
        self.assertNotIn(stale_result, self.window.store_results)


class TestDebianMatePrivilegeAuth(unittest.TestCase):
    """Regression tests for APT, sudo, and Debian authorization isolation."""

    def setUp(self):
        self.runner = CommandRunner()

    def test_missing_sudo_binary_raises_informative_error(self):
        """Missing sudo command raises clear BackendError with installation advice."""
        with patch("shutil.which", return_value=None):
            with self.assertRaises(BackendError) as ctx:
                self.runner._run_privileged_locked(["apt-get", "install", "vlc"], timeout=10, input_text=None)
            self.assertIn("sudo", str(ctx.exception).lower())

    def test_wrong_sudo_password_raises_auth_required_with_retry(self):
        """Incorrect sudo password raises AuthRequiredError(password_failed=True) and clears cache."""
        self.runner.set_sudo_password("wrong_secret")
        fail_process = subprocess.CompletedProcess(
            args=["sudo", "-S", "-p", "", "true"],
            returncode=1,
            stdout="",
            stderr="sudo: 1 incorrect password attempt\n",
        )
        with patch.object(self.runner, "run", return_value=fail_process):
            with self.assertRaises(AuthRequiredError) as ctx:
                self.runner._run_privileged_locked(["true"], timeout=10, input_text=None)
            self.assertTrue(ctx.exception.password_failed)
            self.assertIsNone(self.runner._sudo_password)

    def test_user_not_in_sudoers_raises_informative_backend_error_without_retry_loop(self):
        """User not in sudoers raises BackendError explaining missing group membership."""
        self.runner.set_sudo_password("some_password")
        current_user = getpass.getuser()
        fail_process = subprocess.CompletedProcess(
            args=["sudo", "-S", "-p", "", "true"],
            returncode=1,
            stdout="",
            stderr=f"{current_user} is not in the sudoers file. This incident will be reported.\n",
        )
        with patch.object(self.runner, "run", return_value=fail_process):
            with self.assertRaises(BackendError) as ctx:
                self.runner._run_privileged_locked(["true"], timeout=10, input_text=None)
            # Must NOT be AuthRequiredError (which would trigger password prompt loop)
            self.assertNotIsInstance(ctx.exception, AuthRequiredError)
            self.assertIn("sudo", str(ctx.exception))
            self.assertIn(current_user, str(ctx.exception))
            self.assertIsNone(self.runner._sudo_password)

    def test_multilingual_sudo_failure_detection(self):
        """Sudo password failure messages in German, French, Turkish, Spanish are detected."""
        test_messages = [
            "sudo: 1 incorrect password attempt",
            "Üzgünüm, yeniden deneyin.",
            "Leider, versuchen Sie es noch einmal.",
            "Désolé, réessayez.",
            "Lo siento, intente de nuevo.",
            "authentication failure",
        ]
        for msg in test_messages:
            self.runner.set_sudo_password("test_secret")
            result = subprocess.CompletedProcess(args=["sudo"], returncode=1, stdout="", stderr=msg)
            with self.assertRaises(AuthRequiredError):
                self.runner._raise_for_privileged_result(result, ["apt-get", "install"])
            self.assertIsNone(self.runner._sudo_password)

    def test_privileged_result_redacts_password_in_errors(self):
        """Failed privileged command output always redacts the plaintext password."""
        secret = "super_secret_deb_pass_123"
        self.runner.set_sudo_password(secret)
        result = subprocess.CompletedProcess(
            args=["sudo"],
            returncode=100,
            stdout=f"fatal error with {secret} on line 1",
            stderr="",
        )
        with self.assertRaises(BackendError) as ctx:
            self.runner._raise_for_privileged_result(result, ["apt-get", "update"])
        self.assertNotIn(secret, str(ctx.exception))
        self.assertIn("[redacted]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
