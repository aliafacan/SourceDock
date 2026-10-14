"""Native navigation, discovery, updates and installer contracts using fake providers."""

from dataclasses import replace
import unittest
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk

from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.models import (
    SOURCE_APT,
    SOURCE_FIRMWARE,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    LocalPackageInfo,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.i18n import TRANSLATIONS, t
from sourcedock.preferences import AppPreferences, PreferencesStore
from sourcedock.ui.components.dialogs import AppDetailDialog
from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
from sourcedock.ui.window import MainWindow


class TestUiWorkflows(unittest.TestCase):
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
        preferences = MagicMock(spec=PreferencesStore)
        preferences.load.return_value = AppPreferences("tr", "dark")
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
        self.window.hide()

    def test_navigation_visits_every_page(self):
        self.assertFalse(self.window.pages.get_show_tabs())
        for page in (1, 0, 4, 3, 2):
            self.window.nav_buttons[page].clicked()
            self.assertEqual(self.window.pages.get_current_page(), page)
        self.registry.runner.run_privileged.assert_not_called()

    def test_global_search_filters_the_active_installed_view(self):
        self.window.header_search.set_text("example")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.applications_search_entry.get_text(), "example")

    def test_live_language_switch_updates_navigation_and_categories(self):
        self.window.preferences = AppPreferences("en", "light")
        self.window._refresh_texts()
        self.assertEqual(self.window.nav_labels[4].get_text(), "Updates")
        self.assertEqual(self.window.local_install_label.get_text(), t("en", "install_package_btn"))
        self.assertEqual(self.window.store_category_buttons[0][0].get_label(), "Productivity")

    def test_same_name_different_packages_stay_separate(self):
        first = StoreResult("Editor", "native-editor", "Native", SOURCE_APT, "1", "native")
        second = StoreResult("Editor", "other-editor", "Different", SOURCE_SNAP, "2", "snap-store")
        self.assertEqual(len(self.window._group_store_results([first, second])), 2)
        verified_first = replace(first, identity="org.example.Editor")
        verified_second = replace(second, identity="org.example.Editor")
        self.assertEqual(len(self.window._group_store_results([verified_first, verified_second])), 1)

    def test_same_package_id_from_multiple_sources_is_one_install_choice(self):
        apt = StoreResult("Editor", "editor", "", SOURCE_APT, "1", "apt")
        snap = StoreResult("Editor", "editor", "", SOURCE_SNAP, "2", "snap-store")
        groups = self.window._group_store_results([apt, snap])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0].app_id, "editor")
        self.assertEqual({groups[0][0].source, groups[0][1][0].source}, {SOURCE_APT, SOURCE_SNAP})

    def test_app_detail_dialog_chooses_between_provider_variants(self):
        apt = StoreResult("Editor", "editor", "APT build", SOURCE_APT, "1", "ubuntu")
        snap = StoreResult("Editor", "editor", "Snap build", SOURCE_SNAP, "2", "stable")
        chosen = []
        dialog = AppDetailDialog(
            primary_result=apt,
            all_results=[apt, snap],
            installed_package_ids=set(),
            install_callback=chosen.append,
            language="tr",
            parent=self.window,
        )
        self.addCleanup(dialog.destroy)
        self.assertIsNotNone(dialog._source_combo)
        self.assertEqual(dialog._source_combo.get_model().iter_n_children(None), 2)
        dialog._source_combo.set_active(1)
        self.assertIs(dialog._selected_result, snap)
        dialog._on_install_clicked(None)
        self.assertEqual(chosen, [snap])

    def test_installed_status_is_scoped_to_the_source(self):
        self.window.installed_package_ids = {"apt:editor"}
        result = StoreResult("Editor", "editor", "", SOURCE_SNAP, "1", "snap-store")
        self.assertFalse(self.window._store_result_is_installed(result))
        self.assertTrue(self.window._store_result_is_installed(replace(result, source=SOURCE_APT)))

    def test_discovery_cards_and_error_state(self):
        result = StoreResult(
            "An application with a very long name", "example", "Description", SOURCE_APT, "1", "native"
        )
        self.window._finish_store_search([result], None)
        self.assertEqual(len(self.window.store_cards.get_children()), 1)
        self.assertEqual(self.window.store_state.get_visible_child_name(), "content")
        self.window._finish_store_search([], "Provider offline")
        self.assertEqual(self.window.store_state.get_visible_child_name(), "state")
        self.assertEqual(self.window.store_state.body.get_text(), "Provider offline")

    def test_discovery_card_click_opens_details(self):
        result = StoreResult("Editor", "editor", "Description", SOURCE_APT, "1", "native")
        with patch.object(self.window, "_open_store_detail_dialog") as open_details:
            self.window._finish_store_search([result], None)
            card = self.window.store_cards.get_children()[0].get_child()
            card.clicked()
        open_details.assert_called_once_with(result)

    def _updates(self):
        apps = [
            UnifiedApplication(
                "apt:editor", "Editor", SOURCE_APT, version="1", package_name="editor", update_available=True
            ),
            UnifiedApplication(
                "flatpak:runtime",
                "Runtime",
                SOURCE_FLATPAK,
                version="1",
                package_name="org.example.Platform",
                category="System",
                update_available=True,
            ),
            UnifiedApplication(
                "firmware:device",
                "Device",
                SOURCE_FIRMWARE,
                version="1",
                package_name="device",
                update_available=True,
                update_note="-> 2",
            ),
        ]
        packages = [
            PackageInfo("editor", "1", 1, "Editor", True, "2"),
            PackageInfo("library", "1", 1, "Library", True, "2"),
        ]
        return build_update_catalog(apps, packages, SOURCE_APT)

    def test_updates_group_all_sources_without_duplicate_native_packages(self):
        items = self._updates()
        self.assertEqual({item.group for item in items}, {"applications", "system", "firmware", "runtimes"})
        self.assertEqual(len(items), 4)
        editor = next(item for item in items if item.application.package_name == "editor")
        self.assertEqual(editor.new_version, "2")
        self.window._finish_updates_load(items, [], None)
        self.assertEqual(self.window.updates_stat_labels["applications"][1].get_text(), "1")
        self.assertEqual(self.window.updates_stat_labels["firmware"][1].get_text(), "1")
        self.window.updates_select_all_btn.set_active(True)
        self.assertEqual(len(self.window._selected_updates()), 4)
        self.window._on_update_toggled(None, "0:0")
        self.assertEqual(len(self.window._selected_updates()), 3)

    def test_update_rows_include_application_icons(self):
        items = self._updates()
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
        with patch.object(self.window, "_get_app_pixbuf", return_value=pixbuf):
            self.window._finish_updates_load(items, [], None)
        iterator = self.window.updates_model.get_iter("0:0")
        self.assertIs(self.window.updates_model.get_value(iterator, 6), pixbuf)
        self.assertEqual(self.window.updates_tree.get_grid_lines(), Gtk.TreeViewGridLines.HORIZONTAL)

    def test_firmware_requires_confirmation(self):
        self.window._finish_updates_load(self._updates(), [], None)
        self.window.updates_select_all_btn.set_active(True)
        self.assertTrue(any(item.group == "firmware" for item in self.window._selected_updates()))
        with (
            patch.object(self.window, "_confirm_firmware_update", return_value=False),
            patch.object(self.window, "_run_application_task") as task,
        ):
            self.window._on_apply_updates(None)
        task.assert_not_called()
        self.registry.update.assert_not_called()

    def test_external_processes_cannot_be_paused_or_cancelled(self):
        self.window._external_operations = [("123", "apt-get upgrade")]
        self.window._refresh_operations_list()
        self.window.operations_tree.get_selection().select_path("0")
        self.assertFalse(self.window.operations_cancel_btn.get_sensitive())
        self.assertFalse(self.window.operations_pause_btn.get_sensitive())
        self.window._on_operations_cancel()
        self.registry.runner.cancel_current.assert_not_called()

    def test_system_theme_change_only_affects_system_mode(self):
        with patch.object(self.window, "_apply_theme") as apply:
            self.window.preferences.theme = "system"
            self.window._on_system_theme_changed()
            apply.assert_called_once()
            apply.reset_mock()
            self.window.preferences.theme = "dark"
            self.window._on_system_theme_changed()
            apply.assert_not_called()

    def test_installer_requires_trust_and_does_not_fake_cancellation(self):
        info = LocalPackageInfo("/tmp/test.deb", "deb", "Test", version="1")
        dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
        self.addCleanup(dialog.destroy)
        self.assertFalse(dialog.action_btn.get_sensitive())
        dialog._on_start_install_clicked(None)
        self.assertFalse(dialog._is_installing)
        dialog.trust_check.set_active(True)
        self.assertTrue(dialog.action_btn.get_sensitive())
        dialog._is_installing = True
        self.registry.runner.cancel_current.return_value = False
        dialog._on_cancel_clicked(None)
        self.assertTrue(dialog._is_installing)
        self.assertEqual(dialog.progress_status_label.get_text(), t("tr", "cancel_critical"))

    def test_installer_success_hides_launch_for_a_library(self):
        info = LocalPackageInfo("/tmp/library.deb", "deb", "example-lib", version="1")
        self.registry.runner.command_exists.return_value = False
        dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
        self.addCleanup(dialog.destroy)
        dialog._on_install_success(False)
        self.assertFalse(dialog.launch_btn.get_visible())

    def test_translation_keys_have_parity(self):
        self.assertEqual(set(TRANSLATIONS["tr"]), set(TRANSLATIONS["en"]))


if __name__ == "__main__":
    unittest.main()
