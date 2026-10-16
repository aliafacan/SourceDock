#!/usr/bin/env python3
"""Main window startup and package actions without host package operations."""

import unittest
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from sourcedock.core.models import (
    ApplicationSnapshot,
    PackageInfo,
    SOURCE_APT,
    SOURCE_FLATPAK,
    UnifiedApplication,
)
from sourcedock.i18n import t
from sourcedock.preferences import AppPreferences, PreferencesStore
from sourcedock.ui.window import MainWindow


class TestMainWindowStartup(unittest.TestCase):
    def setUp(self):
        if not Gtk.init_check()[0]:
            self.skipTest("No GUI display available.")

        self.registry = MagicMock()
        self.registry.native_provider.source = SOURCE_APT
        self.registry.native_provider.display_name = "APT"
        preferences = MagicMock(spec=PreferencesStore)
        preferences.load.return_value = AppPreferences(language="tr", theme="dark")

        for mock in (
            patch("sourcedock.ui.window.ApplicationRegistry", return_value=self.registry),
            patch("sourcedock.ui.window.StoreRegistry"),
            patch.object(MainWindow, "reload_applications_async"),
            patch.object(MainWindow, "_reload_updates_async"),
            patch("sourcedock.ui.window.Gtk.main_quit"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

        existing_windows = set(Gtk.Window.list_toplevels())
        self.addCleanup(self._destroy_new_windows, existing_windows)
        self.window = MainWindow(preferences)
        self.window.hide()

    def _destroy_new_windows(self, existing_windows):
        for window in Gtk.Window.list_toplevels():
            if window not in existing_windows:
                window.destroy()

    def _load_packages(self, *names):
        packages = [PackageInfo(name, "1.0", 2048, "Test package", True, "1.1") for name in names]
        self.window._finish_packages_load(packages, None)
        return packages

    def test_main_window_builds_all_pages(self):
        self.assertEqual(self.window.pages.get_n_pages(), 5)
        self.assertEqual(self.window.packages_details_btn.get_label(), t("tr", "applications_details"))
        self.assertEqual(self.window.packages_remove_btn.get_label(), t("tr", "applications_remove"))
        self.assertFalse(self.window.packages_details_btn.get_sensitive())
        self.assertFalse(self.window.packages_remove_btn.get_sensitive())
        self.registry.runner.run_privileged.assert_not_called()

    def test_package_activation_opens_details_for_a_library(self):
        self._load_packages("example-lib")
        with patch.object(self.window, "on_show_application_details") as details:
            self.window.packages_tree.row_activated(
                Gtk.TreePath.new_from_indices([0]),
                self.window.packages_tree_col_name,
            )
        details.assert_called_once()
        application = details.call_args.args[1]
        self.assertEqual(application.package_name, "example-lib")
        self.assertEqual(application.source, SOURCE_APT)
        self.assertEqual(application.version, "1.0")
        self.assertEqual(application.installed_size_kib, 2048)
        self.assertTrue(application.update_available)
        self.assertEqual(application.update_note, "1.1")

    def test_package_single_click_only_selects(self):
        self._load_packages("example-lib")
        with patch.object(self.window, "on_show_application_details") as details:
            self.window.packages_tree.get_selection().select_path("0")
        details.assert_not_called()
        self.assertFalse(self.window.packages_tree.get_activate_on_single_click())

    def test_installed_single_click_only_selects(self):
        application = UnifiedApplication(
            "apt:example",
            "Example",
            SOURCE_APT,
            package_name="example",
            executable="example",
            desktop_file="/usr/share/applications/example.desktop",
        )
        self.window._finish_applications_load(ApplicationSnapshot([application]))
        with patch.object(self.window, "on_show_application_details") as details:
            self.window.applications_tree.get_selection().select_path("0")
        details.assert_not_called()
        self.assertFalse(self.window.applications_tree.get_activate_on_single_click())
        with patch.object(self.window, "on_show_application_details") as details:
            self.window.applications_tree.row_activated(
                Gtk.TreePath.new_from_indices([0]), self.window.applications_tree_col_app
            )
        details.assert_called_once()

    def test_details_button_keeps_the_native_package_identity(self):
        self._load_packages("example")
        self.window.applications = [
            UnifiedApplication("flatpak:example", "Other app", SOURCE_FLATPAK, package_name="example"),
            UnifiedApplication(
                "apt:example",
                "Example",
                SOURCE_APT,
                package_name="example",
                executable="example",
                desktop_file="/usr/share/applications/example.desktop",
            ),
        ]
        self.window.packages_tree.get_selection().select_path("0")
        with patch.object(self.window, "on_show_application_details") as details:
            self.window.packages_details_btn.clicked()
        details.assert_called_once()
        application = details.call_args.args[1]
        self.assertEqual(application.source, SOURCE_APT)
        self.assertEqual(application.name, "Example")
        self.assertEqual(application.executable, "example")
        self.assertEqual(application.version, "1.0")

    def test_remove_button_uses_the_existing_confirmation_flow(self):
        self._load_packages("example-lib")
        self.window.packages_tree.get_selection().select_path("0")
        with patch.object(self.window, "on_remove_application") as remove:
            self.window.packages_remove_btn.clicked()
        remove.assert_called_once()
        application = remove.call_args.args[1]
        self.assertEqual(application.source, SOURCE_APT)
        self.assertEqual(application.package_name, "example-lib")
        self.registry.remove.assert_not_called()
        self.registry.runner.run_privileged.assert_not_called()

    def test_multiple_selection_disables_single_package_actions(self):
        self._load_packages("first", "second")
        selection = self.window.packages_tree.get_selection()
        selection.select_path("0")
        self.assertTrue(self.window.packages_details_btn.get_sensitive())
        self.assertTrue(self.window.packages_remove_btn.get_sensitive())
        selection.select_path("1")
        self.assertFalse(self.window.packages_details_btn.get_sensitive())
        self.assertFalse(self.window.packages_remove_btn.get_sensitive())
        self.assertTrue(self.window.packages_update_btn.get_sensitive())
        with (
            patch.object(self.window, "on_show_application_details") as details,
            patch.object(self.window, "on_remove_application") as remove,
        ):
            self.window._on_packages_details_clicked()
            self.window._on_packages_remove_clicked()
            selection.unselect_all()
            self.window._on_packages_details_clicked()
            self.window._on_packages_remove_clicked()
        details.assert_not_called()
        remove.assert_not_called()

    def test_successful_package_action_refreshes_the_open_packages_page(self):
        self.window.packages = [PackageInfo("example", "1.0", 1, "Test", False)]
        self.window.pages.set_current_page(2)
        with patch.object(self.window, "reload_packages_async") as reload_packages:
            self.window._finish_application_task(True, "Done", True)
        reload_packages.assert_called_once()

    def test_failed_partial_package_action_also_refreshes_measured_state(self):
        self.window.pages.set_current_page(2)
        with patch.object(self.window, "reload_packages_async") as packages, patch.object(self.window, "reload_applications_async") as applications:
            self.window._finish_application_task(False, "A package failed", True)
        packages.assert_called_once()
        applications.assert_called_once()


if __name__ == "__main__":
    unittest.main()
