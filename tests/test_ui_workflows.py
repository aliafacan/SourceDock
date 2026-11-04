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
    ApplicationSnapshot,
    LocalPackageInfo,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.i18n import TRANSLATIONS, t
from sourcedock.preferences import AppPreferences, PreferencesStore
from sourcedock.ui.components.dialogs import AppDetailDialog
from sourcedock.ui.components.common import ScreenshotGallery
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

    def test_logo_toggles_sidebar_on_wide_window(self):
        self.window.resize(1366, 707)
        self.window._on_shell_size_allocate(self.window, self.window.get_allocation())
        self.assertFalse(self.window._compact_sidebar)
        self.window.sidebar_toggle.clicked()
        self.assertTrue(self.window._compact_sidebar)
        self.assertFalse(self.window.brand_label.get_visible())
        self.window.sidebar_toggle.clicked()
        self.assertFalse(self.window._compact_sidebar)
        self.assertTrue(self.window.brand_label.get_visible())

    def test_global_search_filters_the_active_installed_view(self):
        self.window.header_search.set_text("example")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.applications_search_entry.get_text(), "example")

    def test_global_store_search_preserves_header_cursor(self):
        self.window.pages.set_current_page(1)
        self.window._refresh_shell_page(1)
        self.window.header_search.set_text("fire")
        self.window.header_search.set_position(2)
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.header_search.get_position(), 2)
        self.assertEqual(self.window.store_search_entry.get_text(), "fire")

    def test_discover_query_uses_visible_header_as_source_of_truth(self):
        self.window.pages.set_current_page(1)
        self.window.header_search.set_text("firefox")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.store_search_entry.get_text(), "firefox")
        self.window.header_search.set_text("")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.store_search_entry.get_text(), "")

    def test_discover_typing_waits_for_enter_without_debounce(self):
        self.window.pages.set_current_page(1)
        self.window.store_search_entry.set_text("firefox")
        self.assertEqual(self.window._store_search_timeout_id, 0)
        self.store.search.assert_not_called()
        with patch.object(self.window, "on_store_search") as submit:
            self.window._on_global_search_activate(self.window.header_search)
        submit.assert_called_once()

    def test_self_update_reexecutes_the_installed_launcher(self):
        with (
            patch("sourcedock.ui.window.shutil.which", return_value="/usr/bin/sourcedock"),
            patch("sourcedock.ui.window.sys.argv", ["/usr/bin/sourcedock"]),
            patch("sourcedock.ui.window.os.execv") as execv,
        ):
            self.window._on_self_update_installed()

        execv.assert_called_once_with("/usr/bin/sourcedock", ["/usr/bin/sourcedock"])
        self.assertFalse(self.window.get_visible())

    def test_page_search_state_is_scoped_and_restored(self):
        self.window.pages.set_current_page(1)
        self.window.header_search.set_text("firefox")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertEqual(self.window.store_search_entry.get_text(), "firefox")

        self.window.pages.set_current_page(0)
        self.assertEqual(self.window.header_search.get_text(), "")
        self.assertEqual(self.window.applications_search_entry.get_text(), "")
        self.assertTrue(self.window.header_search.get_sensitive())

        self.window.pages.set_current_page(4)
        self.assertEqual(self.window.header_search.get_text(), "")
        self.assertFalse(self.window.header_search.get_sensitive())

        self.window.pages.set_current_page(1)
        self.assertEqual(self.window.header_search.get_text(), "firefox")
        self.assertTrue(self.window.header_search.get_sensitive())

    def test_installed_empty_search_explains_query_and_can_be_cleared(self):
        self.window.applications = [
            UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        ]
        self.window.applications_loading = False
        self.window.header_search.set_text("firefox")
        self.window._on_global_search_changed(self.window.header_search)
        self.assertIn('"firefox"', self.window.installed_state.title.get_text())
        self.assertTrue(self.window.installed_state.retry_button.get_visible())
        self.window.installed_state.retry_button.clicked()
        self.assertEqual(self.window.applications_search_entry.get_text(), "")
        self.assertEqual(self.window.header_search.get_text(), "")
        self.assertEqual(self.window.applications_summary_label.get_text(), "1/1 uygulama gösteriliyor")

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

    def test_firefox_variants_group_but_kiosk_stays_separate(self):
        apt = StoreResult("Firefox", "firefox", "Browser", SOURCE_APT, "1", "apt")
        flatpak = StoreResult("Firefox", "org.mozilla.firefox", "Browser", SOURCE_FLATPAK, "2", "flathub")
        kiosk = StoreResult("Firefox Kiosk", "firefox-kiosk", "Kiosk browser", SOURCE_SNAP, "3", "snap-store")
        groups = self.window._group_store_results([apt, flatpak, kiosk])
        self.assertEqual(len(groups), 2)
        firefox = next(group for group in groups if group[0].name == "Firefox")
        self.assertEqual({firefox[0].source, firefox[1][0].source}, {SOURCE_APT, SOURCE_FLATPAK})

    def test_store_ranking_prioritizes_exact_prefix_then_metadata(self):
        results = [
            StoreResult("Graphics Editor", "graphics-editor", "", SOURCE_APT, "1", "apt", category="Graphics"),
            StoreResult("Editor Suite", "editor-suite", "", SOURCE_APT, "1", "apt"),
            StoreResult("Editor", "editor", "", SOURCE_APT, "1", "apt"),
        ]
        ranked = self.window._group_store_results(results, query="editor")
        self.assertEqual([group[0].app_id for group in ranked], ["editor", "editor-suite", "graphics-editor"])

    def test_store_ranking_uses_exact_match_from_grouped_variant(self):
        primary = StoreResult(
            "Mozilla Browser", "browser", "", SOURCE_APT, "1", "apt", identity="org.mozilla.firefox"
        )
        exact_variant = StoreResult(
            "Firefox", "org.mozilla.firefox", "", SOURCE_FLATPAK, "2", "flathub", identity="org.mozilla.firefox"
        )
        unrelated = StoreResult("Firefox Tools", "firefox-tools", "", SOURCE_APT, "1", "apt")
        groups = self.window._group_store_results([unrelated, primary, exact_variant], query="firefox")
        self.assertEqual(groups[0][0].name, "Firefox")
        self.assertEqual(groups[0][1][0].name, "Mozilla Browser")

    def test_late_store_callback_from_old_query_is_ignored(self):
        old = StoreResult("Old", "old", "", SOURCE_APT, "1", "apt")
        current = StoreResult("Current", "current", "", SOURCE_APT, "1", "apt")
        self.window.store_results = [old]
        self.window._store_search_generation = 2
        self.window._finish_store_search([current], None, generation=1, complete=True)
        self.assertEqual(self.window.store_results, [old])

    def test_app_detail_dialog_chooses_between_provider_variants(self):
        apt = StoreResult(
            "Editor", "editor", "APT build", SOURCE_APT, "1", "ubuntu", publisher="APT Team"
        )
        snap = StoreResult(
            "Editor", "editor", "Snap build", SOURCE_SNAP, "2", "stable", publisher="Snap Team"
        )
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
        self.assertTrue(dialog._source_fields["publisher"][0].get_visible())
        self.assertFalse(dialog._source_fields["license"][0].get_visible())
        dialog._source_combo.set_active(1)
        self.assertIs(dialog._selected_result, snap)
        self.assertEqual(dialog._description_label.get_text(), "Snap build")
        self.assertEqual(dialog._meta_label.get_text(), "Snap  ·  stable  ·  v2")
        self.assertEqual(dialog._source_fields["publisher"][1].get_text(), "Snap Team")
        self.assertTrue(dialog._source_fields["publisher"][0].get_visible())
        dialog._on_install_clicked(None)
        self.assertEqual(chosen, [snap])

    def test_app_detail_dialog_keeps_flatpak_variant_with_apt_and_snap(self):
        apt = StoreResult("Firefox", "firefox", "APT build", SOURCE_APT, "1", "ubuntu")
        snap = StoreResult("Firefox", "firefox", "Snap build", SOURCE_SNAP, "2", "snap-store")
        flatpak = StoreResult(
            "Firefox", "org.mozilla.firefox", "Flatpak build", SOURCE_FLATPAK, "3", "flathub"
        )
        with patch.object(AppDetailDialog, "_load_screenshots_async"):
            dialog = AppDetailDialog(
                primary_result=snap,
                all_results=[apt, snap, flatpak],
                installed_package_ids=set(),
                install_callback=lambda _result: None,
                language="tr",
                parent=self.window,
            )
        self.addCleanup(dialog.destroy)
        self.assertIsNotNone(dialog._source_combo)
        self.assertEqual(dialog._source_combo.get_model().iter_n_children(None), 3)
        dialog._source_combo.set_active(2)
        self.assertEqual(dialog._selected_result.source, SOURCE_FLATPAK)

    def test_screenshot_gallery_ends_hidden_without_spinner_or_late_callback_crash(self):
        gallery = ScreenshotGallery(["https://example.test/missing.png"], "tr")
        self.addCleanup(gallery.destroy)
        gallery._finish([])
        self.assertFalse(gallery.get_visible())
        gallery._on_destroy(gallery)
        self.assertFalse(gallery._finish([GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)]))

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
        self.assertNotIn("Provider offline", self.window.store_state.body.get_text())
        self.assertIn(t("tr", "store_search_retry_hint"), self.window.store_state.body.get_text())

    def test_store_provider_errors_are_shown_once(self):
        result = StoreResult("Firefox", "firefox", "Browser", SOURCE_APT, "1", "apt")
        self.window.store_registry.provider_errors = [
            "APT: timeout",
            "APT: timeout",
            "FLATPAK: timeout",
        ]
        self.window.store_registry.last_search_source_states = {
            SOURCE_APT: "unavailable",
            SOURCE_FLATPAK: "unavailable",
        }
        self.window._finish_store_search([result], None)
        status = self.window.store_status.get_text()
        self.assertIn("Yanıt alınamadı: APT, Flatpak", status)
        self.assertEqual(status.count("Yanıt alınamadı:"), 1)
        self.assertNotIn("APT: timeout", status)
        self.assertIn("doğrulanamadı", self.window._display_store_source(result))

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
        self.assertEqual(self.window.updates_tree.get_grid_lines(), Gtk.TreeViewGridLines.NONE)
        self.assertFalse(self.window.updates_toggle_renderer.get_property("radio"))

    def test_update_summary_filter_can_return_to_all_groups(self):
        self.window._finish_updates_load(self._updates(), [], None)
        self.assertEqual(self.window.updates_model.iter_n_children(None), 4)

        self.window.updates_stat_buttons["applications"].clicked()
        self.assertEqual(self.window.updates_active_group, "applications")
        self.assertEqual(self.window.updates_model.iter_n_children(None), 1)
        self.assertTrue(self.window.updates_show_all_btn.get_sensitive())

        self.window.updates_show_all_btn.clicked()
        self.assertIsNone(self.window.updates_active_group)
        self.assertEqual(self.window.updates_model.iter_n_children(None), 4)
        self.assertFalse(self.window.updates_show_all_btn.get_visible())

    def test_update_group_toggle_selects_only_supported_children(self):
        self.window._finish_updates_load(self._updates(), [], None)
        group_iterator = self.window.updates_model.get_iter("0")
        self.assertIsNone(self.window.updates_model.get_value(group_iterator, 5))

        self.window._on_update_toggled(None, "0")
        self.assertEqual(len(self.window._selected_updates()), 1)
        child_iterator = self.window.updates_model.iter_children(group_iterator)
        self.assertTrue(self.window.updates_model.get_value(child_iterator, 0))

    def test_bulk_remove_is_enabled_only_for_removable_selection(self):
        app = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        self.window.applications = [app]
        self.window.applications_loading = False
        self.window._render_applications_list()
        self.window.applications_tree.get_selection().select_path("0")
        self.assertTrue(self.window.applications_bulk_remove_btn.get_sensitive())

        firmware = UnifiedApplication("firmware:device", "Device", SOURCE_FIRMWARE, package_name="device")
        self.window.applications = [firmware]
        self.window._render_applications_list()
        self.window.applications_tree.get_selection().select_path("0")
        self.assertFalse(self.window.applications_bulk_remove_btn.get_sensitive())

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

    def test_update_provider_notice_is_compact_with_hidden_details(self):
        self.window._finish_updates_load(
            self._updates(),
            ["apt (sistem): 42 arayüzsüz paket güncellenebilir → apache2, curl"],
            None,
        )

        self.assertTrue(self.window.updates_status_panel.get_visible())
        self.assertEqual(self.window.updates_status.get_text(), "APT: 42 sistem paketi güncellenebilir")
        self.assertNotIn("apache2", self.window.updates_status.get_text())
        self.assertFalse(self.window.updates_status_details.get_visible())
        self.window.updates_status_details_btn.clicked()
        self.assertTrue(self.window.updates_status_details.get_visible())
        self.assertIn("apache2", self.window.updates_status_details.get_text())

    def test_system_package_notice_does_not_claim_a_provider_failed(self):
        notice = "apt (sistem): 42 arayüzsüz paket güncellenebilir → apache2, curl"
        application = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        self.window._finish_applications_load(ApplicationSnapshot([application], provider_notices=[notice]))
        self.assertEqual(self.window.application_provider_errors, [])
        self.assertNotIn("okunamadı", self.window.applications_status.get_text())
        self.window.preferences.language = "en"
        self.window._refresh_texts()
        self.assertEqual(self.window.applications_diagnostics_label.get_text(), "1 diagnostic record:")
        diagnostic = self.window.applications_diagnostics_list.get_children()[0].get_child()
        self.assertIn("42 system packages", diagnostic.get_children()[1].get_text())

    def test_select_all_reflects_partial_and_individual_selection(self):
        items = self._updates()
        self.window._finish_updates_load(items, [], None)
        self.window._on_update_toggled(None, "0:0")
        self.assertTrue(self.window.updates_select_all_btn.get_inconsistent())
        self.assertFalse(self.window.updates_select_all_btn.get_active())
        self.window.updates_select_all_btn.set_active(True)
        self.assertEqual(len(self.window._selected_updates()), len(items))
        self.assertFalse(self.window.updates_select_all_btn.get_inconsistent())
        self.window._on_update_toggled(None, "0:0")
        self.assertEqual(len(self.window._selected_updates()), len(items) - 1)
        self.assertTrue(self.window.updates_select_all_btn.get_inconsistent())

    def test_selected_updates_use_one_batched_registry_operation(self):
        from sourcedock.core.errors import BackendError

        self.window._finish_updates_load(self._updates(), [], None)
        self.window.updates_select_all_btn.set_active(True)
        with patch.object(self.window, "_confirm_firmware_update", return_value=True), patch.object(self.window, "_run_application_task") as start:
            self.window._on_apply_updates(None)
        worker = start.call_args.args[1]

        self.registry.update_all.side_effect = BackendError("batched update failed")
        with patch("sourcedock.ui.views.updates_view.GLib.idle_add"), self.assertRaises(BackendError):
            worker()
        self.registry.update_all.assert_called_once()
        applications = self.registry.update_all.call_args.args[0]
        self.assertEqual(len(applications), 4)
        self.assertEqual({app.package_name for app in applications}, {"editor", "library", "org.example.Platform", "device"})
        self.registry.update_all.reset_mock(side_effect=True)
        with patch("sourcedock.ui.views.updates_view.GLib.idle_add"):
            worker()
        self.registry.update_all.assert_called_once()

    def test_cleanup_cancel_never_starts_an_operation(self):
        from sourcedock.backend.flatpak_cleanup import CleanupRef

        with patch("sourcedock.ui.views.installed_view.Gtk.Dialog.run", return_value=Gtk.ResponseType.CANCEL), patch.object(self.window, "_run_application_task") as run:
            self.window._show_flatpak_cleanup_plan(
                (CleanupRef("user", "runtime/org.example.Runtime/x86_64/stable"),), None,
            )
        run.assert_not_called()

    def test_bulk_updates_keep_both_flatpak_scopes_and_remove_real_duplicates(self):
        import os
        from types import SimpleNamespace

        user = UnifiedApplication(
            "flatpak:org.example.Editor", "Editor", SOURCE_FLATPAK,
            package_name="org.example.Editor",
            install_path=os.path.expanduser("~/.local/share/flatpak/app/org.example.Editor"),
        )
        system = replace(user, install_path="/var/lib/flatpak/app/org.example.Editor")
        with patch.object(self.window, "_selected_updates", return_value=[
            SimpleNamespace(application=app, group="applications") for app in (user, system, user)
        ]), patch.object(self.window, "_run_application_task") as start:
            self.window._on_apply_updates(None)
        start.call_args.args[1]()
        self.registry.update_all.assert_called_once_with([user, system])

    def test_technical_package_setting_refilters_existing_store_results(self):
        self.window.store_layout_toggle.set_active(True)
        self.window.store_search_entry.set_text("wireshark")
        self.window.store_results = [
            StoreResult("Wireshark", "wireshark", "Analyzer", SOURCE_APT, "1", "apt"),
            StoreResult("Documentation", "wireshark-doc", "Documentation", SOURCE_APT, "1", "apt", is_application=False),
        ]
        self.window._render_store_results(self.window.store_results)
        self.assertEqual(len(self.window.store_results_store), 1)

        def save_settings(dialog):
            def visit(widget):
                if isinstance(widget, Gtk.CheckButton) and widget.get_label() == t("tr", "settings_show_technical_packages"):
                    widget.set_active(True)
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        visit(child)
            visit(dialog)
            return Gtk.ResponseType.OK

        with (
            patch("sourcedock.ui.views.settings_view.Gtk.Dialog.run", save_settings),
            patch("sourcedock.ui.views.settings_view.is_default_package_handler", return_value=False),
        ):
            self.window.on_open_settings(None)
        self.assertTrue(self.window.preferences.show_technical_packages)
        self.assertEqual(len(self.window.store_results_store), 2)

    def test_exact_technical_search_is_visible_with_setting_disabled(self):
        technical = StoreResult("Documentation", "wireshark-doc", "Documentation", SOURCE_APT, "1", "apt", is_application=False)
        self.window.preferences.show_technical_packages = False
        self.assertTrue(self.window._is_store_result_visible(technical, "Wireshark-Doc"))
        self.assertFalse(self.window._is_store_result_visible(technical, "wireshark"))
        self.window.preferences.show_technical_packages = True
        self.assertTrue(self.window._is_store_result_visible(technical, "wireshark"))

    def test_progress_details_follow_preference_and_remain_manually_toggleable(self):
        from sourcedock.ui.components.progress import OperationProgressWindow

        for expanded in (False, True):
            with self.subTest(expanded=expanded):
                self.window.preferences.show_operation_details_by_default = expanded
                runner = self.registry.runner
                with patch("sourcedock.ui.views.installed_view.threading.Thread"):
                    self.window._run_application_task("update", lambda: None, "packages_update_done", "nav_updates")
                progress = next(
                    window for window in Gtk.Window.list_toplevels() if isinstance(window, OperationProgressWindow)
                )
                try:
                    self.assertIs(progress._details_expander.get_expanded(), expanded)
                    progress._details_expander.set_expanded(not expanded)
                    self.assertIs(progress._details_expander.get_expanded(), not expanded)
                finally:
                    progress.destroy()
                    self.window.applications_busy = False
                    runner.set_output_callback(None)

    def test_quiet_inventory_adds_installs_and_keeps_unrelated_update_choices(self):
        from sourcedock.backend.updates import UpdateItem

        old = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor", version="1", update_available=True)
        added = UnifiedApplication("flatpak:new", "New App", SOURCE_FLATPAK, package_name="org.example.New", desktop_file="new.desktop")
        self.window.applications = [old]
        self.window._finish_updates_load([UpdateItem(old, "applications", "2")], [], None)
        self.window.updates_select_all_btn.set_active(True)
        self.window._quiet_refresh_generation = 1
        with patch.object(self.window.installed_state, "show_state") as loading, patch.object(self.window, "_load_update_status_for_installed") as scan:
            self.window._apply_quiet_inventory(1, ApplicationSnapshot([replace(old, update_available=False), added]), [], set())
        self.assertEqual([app.id for app in self.window.applications], [old.id, added.id])
        self.assertTrue(self.window.applications[0].update_available)
        self.assertEqual([item.application.id for item in self.window._selected_updates()], [old.id])
        loading.assert_not_called()
        scan.assert_not_called()

    def test_quiet_inventory_resolves_only_successful_update_targets(self):
        from sourcedock.backend.updates import UpdateItem

        for source in (SOURCE_APT, "dnf", "pacman", "zypper", SOURCE_FLATPAK, SOURCE_SNAP, "portable"):
            with self.subTest(source=source):
                changed = UnifiedApplication(f"{source}:editor", "Editor", source, package_name="editor", version="1", update_available=True)
                other = UnifiedApplication("apt:other", "Other", SOURCE_APT, package_name="other", version="1", update_available=True)
                self.window.applications = [changed, other]
                self.window.update_items = [UpdateItem(changed, "applications", "2"), UpdateItem(other, "system", "2")]
                self.window._quiet_refresh_generation = 1
                self.window._apply_quiet_inventory(1, ApplicationSnapshot([replace(changed, version="2"), other]), [], {self.window._inventory_identity(changed)})
                self.assertFalse(self.window.applications[0].update_available)
                self.assertEqual([item.application.id for item in self.window.update_items], [other.id])

    def test_quiet_inventory_retains_failed_sources_and_ignores_stale_reads(self):
        from sourcedock.backend.updates import UpdateItem

        old = UnifiedApplication("snap:editor", "Editor", SOURCE_SNAP, package_name="editor", update_available=True)
        self.window.applications = [old]
        self.window.update_items = [UpdateItem(old, "applications")]
        self.window._quiet_refresh_generation = 2
        self.window._apply_quiet_inventory(1, ApplicationSnapshot([]), [], set())
        self.assertEqual(self.window.applications, [old])
        self.window._apply_quiet_inventory(2, ApplicationSnapshot([], provider_errors=["snap: timeout"]), None, set())
        self.assertEqual(self.window.applications, [old])
        self.assertEqual(len(self.window.update_items), 1)

    def test_quiet_inventory_worker_never_requests_update_discovery(self):
        self.registry.providers = [MagicMock(source=SOURCE_APT), MagicMock(source=SOURCE_SNAP)]
        self.registry.load_sources.return_value = ApplicationSnapshot([])
        self.registry.list_packages.return_value = []
        scan_token = self.window._application_update_scan_token
        with patch("sourcedock.ui.views.installed_view.threading.Thread") as thread, patch("sourcedock.ui.views.installed_view.GLib.idle_add"):
            self.window._refresh_inventory_quietly()
            thread.call_args.kwargs["target"]()
        self.registry.load_sources.assert_called_once_with({SOURCE_APT, SOURCE_SNAP})
        self.registry.load.assert_not_called()
        self.registry.list_packages.assert_called_once_with(include_updates=False)
        self.assertGreater(self.window._application_update_scan_token, scan_token)
        self.assertFalse(self.window._application_initial_load_needs_updates)
        self.window.reload_applications_async.assert_called_once()  # Initial window construction only.

    def test_store_install_finishes_with_a_quiet_inventory_refresh(self):
        with patch.object(self.window, "_refresh_inventory_quietly") as refresh:
            self.window._finish_store_install(True, "Done")
        refresh.assert_called_once_with(sources=None)

    def test_common_progress_reports_running_elapsed_time_and_provider_percentages(self):
        from sourcedock.ui.components.progress import OperationProgressWindow

        progress = OperationProgressWindow("Test", "Demo", self.window, language="en")
        self.addCleanup(progress.destroy)
        for source in ("snap", "apt-get", "dnf", "pacman", "zypper", "flatpak"):
            with self.subTest(source=source):
                progress.append_log(f"SOURCEDOCK_PHASE running {source}")
                self.assertEqual(progress._title_label.get_text(), t("en", "progress_running"))
                with patch("sourcedock.ui.components.progress.time.monotonic", return_value=progress._phase_started + 10):
                    progress._expire_measurement()
                self.assertIn("0:10", progress._status_label.get_text())
                progress.append_log("Downloading package 42% 1MB/s")
                self.assertAlmostEqual(progress._progress.get_fraction(), .42)
        buffer = progress._log_buf
        logs = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        self.assertNotIn("SOURCEDOCK_PHASE", logs)
        self.registry.runner.run_privileged.assert_not_called()

    def test_installed_details_are_shown_without_reentering_modal_run(self):
        application = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        with patch("sourcedock.ui.views.installed_view.InstalledAppDetailsDialog") as details:
            self.window.on_show_application_details(None, application)
        details.return_value.run.assert_not_called()
        details.return_value.show_all.assert_called_once()

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

    def test_confirmed_removal_updates_rows_without_a_reload_or_update_scan(self):
        from sourcedock.backend.updates import UpdateItem

        removed = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor", update_available=True)
        remaining = UnifiedApplication("apt:other", "Other", SOURCE_APT, package_name="other", update_available=True)
        self.window.applications = [removed, remaining]
        self.window.packages = [PackageInfo("editor", "1", 1, "", True, "2"), PackageInfo("other", "1", 1, "", True, "2")]
        self.window._render_applications_list()
        self.window._finish_updates_load([UpdateItem(removed, "applications"), UpdateItem(remaining, "applications")], [], None)
        self.window.updates_select_all_btn.set_active(True)
        self.window.reload_applications_async.reset_mock()
        self.window._reload_updates_async.reset_mock()
        with patch.object(self.window, "_load_update_status_for_installed") as scan:
            self.window._forget_removed_applications([removed])
        self.assertEqual(self.window.applications, [remaining])
        self.assertEqual([row[9].id for row in self.window.applications_store], [remaining.id])
        self.assertEqual([pkg.name for pkg in self.window.packages], ["other"])
        self.assertEqual([item.application for item in self.window._selected_updates()], [remaining])
        self.window.reload_applications_async.assert_not_called()
        self.window._reload_updates_async.assert_not_called()
        scan.assert_not_called()

    def test_removal_only_prunes_rows_after_success(self):
        app = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        self.window.applications = [app]
        with (
            patch("sourcedock.ui.views.installed_view.Gtk.Dialog.run", return_value=Gtk.ResponseType.OK),
            patch.object(self.window, "_run_application_task") as start,
        ):
            self.window.on_remove_application(None, app)
        arguments = start.call_args.kwargs
        self.assertFalse(arguments["refresh_after"])
        self.registry.remove.side_effect = RuntimeError("failed")
        with self.assertRaises(RuntimeError):
            arguments["worker_callable"]()
        self.assertEqual(self.window.applications, [app])
        self.registry.remove.side_effect = None
        arguments["worker_callable"]()
        self.assertEqual(self.window.applications, [app])
        arguments["on_success"]()
        self.assertEqual(self.window.applications, [])

    def test_removing_one_flatpak_scope_keeps_the_other_installation(self):
        user = UnifiedApplication("flatpak:editor", "Editor", SOURCE_FLATPAK, package_name="org.example.Editor", install_path="/home/example/.local/share/flatpak/app/editor")
        system = replace(user, install_path="/var/lib/flatpak/app/editor")
        self.window.applications = [user, system]
        self.window._forget_removed_applications([user])
        self.assertEqual(self.window.applications, [system])

    def test_removal_success_hook_waits_for_a_successful_result_including_lingering(self):
        import threading
        from types import SimpleNamespace
        from sourcedock.core.errors import BackendError

        for outcome in ("success", "failure", "lingering"):
            with self.subTest(outcome=outcome):
                completed = threading.Event()
                completed.set()
                runner = self.registry.runner
                runner.get_operation_context.return_value = (
                    SimpleNamespace(lingering=True, completed_event=completed, returncode=0)
                    if outcome == "lingering" else None
                )
                callback = MagicMock()
                operation = MagicMock(side_effect=BackendError("timeout") if outcome != "success" else None)
                with (
                    patch("sourcedock.ui.views.installed_view.OperationProgressWindow"),
                    patch("sourcedock.ui.views.installed_view.threading.Thread") as thread,
                    patch("sourcedock.ui.views.installed_view.GLib.idle_add", lambda function, *args: function(*args)),
                ):
                    self.window._run_application_task("remove", operation, "applications_remove_done", "applications_progress_remove", on_success=callback)
                    callback.assert_not_called()
                    thread.call_args.kwargs["target"]()
                operation.assert_called_once()
                if outcome == "failure":
                    callback.assert_not_called()
                else:
                    callback.assert_called_once()
                self.assertFalse(self.window.applications_busy)

    def test_installer_auth_retry_starts_a_new_attempt(self):
        info = LocalPackageInfo("/tmp/test.deb", "deb", "Test", version="1")
        dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
        self.addCleanup(dialog.destroy)
        dialog._is_installing = True

        with (
            patch.object(Gtk.Dialog, "run", return_value=Gtk.ResponseType.OK),
            patch.object(Gtk.Entry, "get_text", return_value="test-password"),
            patch.object(dialog, "_start_installation") as start,
        ):
            dialog._prompt_auth_and_retry()

        self.assertFalse(dialog._is_installing)
        start.assert_called_once()

    def test_installer_success_hides_launch_for_a_library(self):
        info = LocalPackageInfo("/tmp/library.deb", "deb", "example-lib", version="1")
        self.registry.runner.command_exists.return_value = False
        dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
        self.addCleanup(dialog.destroy)
        dialog._on_install_success(False)
        self.assertFalse(dialog.launch_btn.get_visible())

    def test_local_installer_uses_saved_details_preference(self):
        info = LocalPackageInfo("/tmp/test.deb", "deb", "Test", version="1")
        for expanded in (False, True):
            with self.subTest(expanded=expanded), patch(
                "sourcedock.ui.components.package_installer_dialog.PreferencesStore.load",
                return_value=replace(AppPreferences("en", "dark"), show_operation_details_by_default=expanded),
            ):
                dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
                try:
                    self.assertIs(dialog.log_expander.get_expanded(), expanded)
                    dialog.log_expander.set_expanded(not expanded)
                    self.assertIs(dialog.log_expander.get_expanded(), not expanded)
                finally:
                    dialog.destroy()

    def test_installer_preserves_source_when_trash_is_unavailable_or_fails(self):
        import tempfile
        from pathlib import Path
        from sourcedock.core.errors import BackendError

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.deb"
            path.write_bytes(b"installer fixture")
            info = LocalPackageInfo(str(path), "deb", "Test", version="1")
            dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
            self.addCleanup(dialog.destroy)
            for available in (False, True):
                with self.subTest(gio_available=available):
                    self.registry.runner.command_exists.return_value = available
                    self.registry.runner.run.side_effect = BackendError("Trash unavailable")
                    with (
                        patch("sourcedock.ui.components.package_installer_dialog.GLib.idle_add", lambda callback: callback()),
                        patch.object(dialog, "_on_install_success") as success,
                        patch.object(dialog, "_on_install_failure") as failure,
                    ):
                        dialog._worker_install(None, True, "--user", False, True)
                    success.assert_called_once_with(False)
                    failure.assert_not_called()
                    self.assertEqual(path.read_bytes(), b"installer fixture")

    def test_translation_keys_have_parity(self):
        self.assertEqual(set(TRANSLATIONS["tr"]), set(TRANSLATIONS["en"]))

    def test_installed_grid_layout_toggle(self):
        app = UnifiedApplication(
            id="test.editor",
            name="Test Editor",
            source="flatpak",
            version="2.0",
            package_name="test.editor",
            desktop_file="/usr/share/applications/test.editor.desktop",
        )

        self.window.applications = [app]
        self.window.applications_loading = False
        self.window._render_applications_list()

        # By default, layout is table
        self.assertEqual(self.window.applications_view_stack.get_visible_child_name(), "table")
        self.assertTrue(self.window.applications_table_toggle.get_sensitive())

        # Toggle to grid layout
        self.window.applications_layout_toggle.set_active(True)
        self.assertEqual(self.window.applications_view_stack.get_visible_child_name(), "cards")
        self.assertFalse(self.window.applications_table_toggle.get_sensitive())

        # Verify cards were created
        cards = self.window.applications_cards.get_children()
        self.assertEqual(len(cards), 1)
        card = cards[0].get_child()
        self.assertIn("Test Editor", card.get_accessible().get_name())


        # Clicking card invokes details
        with patch.object(self.window, "on_show_application_details") as details_mock:
            card.clicked()
            details_mock.assert_called_once_with(None, app)

        # Toggle back to table
        self.window.applications_layout_toggle.set_active(False)
        self.assertEqual(self.window.applications_view_stack.get_visible_child_name(), "table")
        self.assertTrue(self.window.applications_table_toggle.get_sensitive())



    def test_show_technical_packages_setting_toggle(self):
        """Ayarlardaki 'Teknik kaynak ve çalışma zamanı öğelerini göster' seçeneği
        masaüstü dosyası olmayan Flatpak/Snap/Firmware öğelerini listeye dahil eder."""
        from sourcedock.core.models import SOURCE_FLATPAK

        normal_app = UnifiedApplication(
            id="app.regular",
            name="Regular App",
            source=SOURCE_FLATPAK,
            version="1.0",
            package_name="app.regular",
            desktop_file="/usr/share/applications/app.regular.desktop",
        )
        technical_pkg = UnifiedApplication(
            id="org.freedesktop.Platform",
            name="Freedesktop Platform",
            source=SOURCE_FLATPAK,
            version="23.08",
            package_name="org.freedesktop.Platform",
            desktop_file="",  # Teknik çalışma zamanı (kısayolu yok)
        )

        self.window.applications = [normal_app, technical_pkg]
        self.window.applications_loading = False
        self.window.application_filter_source = "all"
        self.window.application_filter_category = "__all__"
        self.window.application_search_text = ""

        # 1. Varsayılan durum: show_technical_packages=False (teknik öğe gizli)
        self.window.preferences.show_technical_packages = False
        self.window._render_applications_list()
        self.assertEqual(len(self.window.filtered_applications), 1)
        self.assertEqual(self.window.filtered_applications[0].id, "app.regular")
        summary_text = self.window.applications_summary_label.get_text()
        self.assertIn("1/2", summary_text)
        self.assertIn("1", summary_text)  # 1 teknik kaynak öğesi gizli
        self.assertIsNotNone(self.window.applications_summary_label.get_tooltip_text())

        # 2. Seçenek aktif edildiğinde: show_technical_packages=True (tüm 2 öğe de gösterilir)
        self.window.preferences.show_technical_packages = True
        self.window._render_applications_list()
        self.assertEqual(len(self.window.filtered_applications), 2)
        summary_text_all = self.window.applications_summary_label.get_text()
        self.assertIn("2/2", summary_text_all)
        self.assertNotIn("gizli", summary_text_all)
        self.assertNotIn("hidden", summary_text_all)

    def test_action_bars_hidden_when_empty_to_prevent_negative_allocation(self) -> None:
        """Boş action-bar bileşenlerinin gizlenerek negatif CSS gadget tahsis uyarısını önlediğini doğrular."""
        # Başlangıçta store_action_bar çocukları görünür olmadığı için bar da gizlidir
        self.assertFalse(self.window.store_action_bar.get_visible())

        # Yükle butonu veya durum etiketi görünür olduğunda action bar görünür olmalı
        self.window.store_install_btn.set_visible(True)
        self.assertTrue(self.window.store_action_bar.get_visible())

        self.window.store_install_btn.set_visible(False)
        self.assertFalse(self.window.store_action_bar.get_visible())

        self.window.store_status.set_visible(True)
        self.assertTrue(self.window.store_action_bar.get_visible())

        self.window.store_status.set_visible(False)
        self.assertFalse(self.window.store_action_bar.get_visible())

        # İşlemler sayfası: iptal butonu gizliyken bar gizli, görünürken görünür olmalı
        self.assertFalse(self.window.operations_action_bar.get_visible())
        self.window.operations_cancel_btn.set_visible(True)
        self.assertTrue(self.window.operations_action_bar.get_visible())

        self.window.operations_cancel_btn.set_visible(False)
        self.assertFalse(self.window.operations_action_bar.get_visible())


    def test_system_filter_is_available_without_showing_technical_packages(self):
        runtime = UnifiedApplication("flatpak:runtime", "Platform", SOURCE_FLATPAK,
                                     package_name="org.example.Platform", category="System")
        normal = replace(runtime, id="flatpak:editor", name="Editor", category="Utility", desktop_file="editor.desktop")
        self.window.applications = [normal, runtime]
        self.window.preferences.show_technical_packages = False
        self.window.application_filter_source = "system"
        self.assertIn("system", self.window.application_filter_buttons)
        self.assertEqual(self.window._filtered_application_items(), [runtime])
        self.assertEqual(self.window._application_source_label("system"), "Sistem")

    def test_system_removal_requires_exact_package_name(self):
        from sourcedock.ui.components.removal import add_sensitive_removal_confirmation
        runtime = UnifiedApplication("snap:core22", "core22", SOURCE_SNAP,
                                     package_name="core22", category="System")
        box, button = Gtk.Box(), Gtk.Button()
        add_sensitive_removal_confirmation(box, button, [runtime], "tr")
        self.assertFalse(button.get_sensitive())
        entry = next(child for child in box.get_children() if isinstance(child, Gtk.Entry))
        entry.set_text("core")
        self.assertFalse(button.get_sensitive())
        entry.set_text("core22")
        self.assertTrue(button.get_sensitive())
        self.assertTrue(any("bağlı uygulamaların" in child.get_text()
                            for child in box.get_children() if isinstance(child, Gtk.Label)))

    def test_filters_and_search_stay_usable_during_multiple_tasks(self):
        from sourcedock.ui.components.progress import OperationProgressWindow
        with patch("sourcedock.ui.views.installed_view.threading.Thread") as threads:
            self.window._run_application_task("update", lambda: None, "packages_update_done", "nav_updates")
            self.window._run_application_task("remove", lambda: None, "applications_remove_done", "applications_progress_remove")
        self.assertEqual(threads.call_count, 2)
        self.assertEqual(self.window._application_task_count, 2)
        self.assertTrue(self.window.applications_search_entry.get_sensitive())
        self.assertTrue(all(button.get_sensitive() for button in self.window.application_filter_buttons.values()))
        self.window._finish_application_task(True, "Done", False)
        self.assertTrue(self.window.applications_busy)
        self.window._finish_application_task(True, "Done", False)
        self.assertFalse(self.window.applications_busy)
        for window in Gtk.Window.list_toplevels():
            if isinstance(window, OperationProgressWindow):
                window.destroy()

    def test_scoped_snapshot_preserves_unrelated_system_rows(self):
        runtime = UnifiedApplication("flatpak:runtime", "Platform", SOURCE_FLATPAK,
                                     package_name="org.example.Platform", category="System")
        snap = UnifiedApplication("snap:editor", "Editor", SOURCE_SNAP, package_name="editor")
        self.window.applications = [runtime, snap]
        snapshot = ApplicationSnapshot([replace(snap, version="2")])
        self.window._quiet_refresh_generation = 1
        self.window._apply_quiet_inventory(1, snapshot, None, set(), sources={SOURCE_SNAP})
        self.assertIn(runtime, self.window.applications)
        self.assertEqual(next(app for app in self.window.applications if app.source == SOURCE_SNAP).version, "2")

    def test_concurrent_removal_is_not_resurrected_by_an_earlier_inventory_read(self):
        app = UnifiedApplication("snap:editor", "Editor", SOURCE_SNAP, package_name="editor")
        self.window.applications = [app]
        self.window._quiet_refresh_generation = 1
        self.window._forget_removed_applications([app])
        self.window._apply_quiet_inventory(1, ApplicationSnapshot([app]), None, set(), sources={SOURCE_SNAP})
        self.assertEqual(self.window.applications, [])
        # A later install with the same identity is a new authoritative query.
        self.window._quiet_refresh_generation = 2
        self.window._apply_quiet_inventory(2, ApplicationSnapshot([app]), None, set(), sources={SOURCE_SNAP})
        self.assertEqual(self.window.applications, [app])

    def test_flatpak_progress_has_no_duplicate_terminal_bar(self):
        from sourcedock.ui.components.progress import OperationProgressWindow
        progress = OperationProgressWindow("Test", "Editor", self.window, language="tr")
        self.addCleanup(progress.destroy)
        progress.append_log("SOURCEDOCK_PHASE running flatpak")
        progress.append_log("Güncelleniyor 1/8… ██████████       51% 625,4 kB/s 00:03")
        self.assertAlmostEqual(progress._progress.get_fraction(), .51)
        self.assertNotIn("█", progress._status_label.get_text())
        self.assertNotIn("51%", progress._status_label.get_text())
        self.assertIn("625,4 kB/s", progress._status_label.get_text())
        self.assertIn("1/8", progress._title_label.get_text())
        progress.append_log("43% 511,8 kB/s 00:05")
        buf = progress._log_buf
        self.assertNotIn("█", buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
        progress.append_log("error: download failed")
        self.assertIn("download failed", buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))

    def test_fast_archive_inspection_does_not_flash_loading_dialog(self):
        from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
        info = LocalPackageInfo("/tmp/editor.tar.gz", "archive", "Editor")
        registry = MagicMock()
        registry.inspect_local_package.return_value = info
        with (patch("sourcedock.ui.views.installed_view.threading.Thread") as thread,
              patch("sourcedock.backend.manager.ApplicationRegistry", return_value=registry),
              patch("sourcedock.ui.views.installed_view.PackageInstallerDialog", spec=PackageInstallerDialog) as preview,
              patch("sourcedock.ui.views.installed_view.GLib.idle_add", side_effect=lambda fn, *args: fn(*args))):
            self.window.prompt_and_install_file(info.file_path)
            loading = next(window for window in Gtk.Window.list_toplevels()
                           if window.get_title() == t("tr", "package_inspecting"))
            self.assertFalse(loading.get_visible())
            thread.call_args.kwargs["target"]()
            preview.assert_called_once()
            preview.return_value.show_all.assert_called_once()


    def test_chrome_detail_shows_installed_source_and_explicit_migration(self):
        from sourcedock.core.models import SOURCE_APT
        from tests.test_source_switch import chrome
        target = StoreResult("Google Chrome", "com.google.Chrome", "Browser", SOURCE_FLATPAK, "2", "flathub")
        native = replace(target, source=SOURCE_APT, app_id="google-chrome-stable", remote="apt")
        installed = chrome()
        installs, switches = [], []
        with patch.object(AppDetailDialog, "_load_screenshots_async"):
            dialog = AppDetailDialog(target, [target, native], {"apt:google-chrome-stable"}, installs.append,
                                     "tr", self.window, installed_applications=[installed],
                                     switch_callback=lambda *args: switches.append(args))
        self.addCleanup(dialog.destroy)
        self.assertIn("APT", dialog._installed_elsewhere_label.get_text())
        self.assertTrue(dialog._installed_elsewhere_label.get_visible())
        self.assertTrue(dialog._switch_btn.get_visible())
        self.assertEqual(dialog._install_btn.get_label(), "Ayrıca kur")
        self.assertEqual(dialog._source_combo.get_model().iter_n_children(None), 2)
        dialog._source_combo.set_active(1)
        self.assertFalse(dialog._install_btn.get_sensitive())
        self.assertFalse(dialog._switch_btn.get_visible())
        dialog._source_combo.set_active(0)
        dialog._on_switch_clicked(None)
        self.assertEqual(switches, [(target, [installed])])
        self.assertEqual(installs, [])

    def test_open_store_details_receive_late_installed_inventory(self):
        from tests.test_source_switch import chrome
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        with patch.object(AppDetailDialog, "_load_screenshots_async"):
            dialog = AppDetailDialog(target, [target], set(), lambda _result: None,
                                     "tr", self.window, switch_callback=lambda *_args: None)
        self.addCleanup(dialog.destroy)
        self.assertFalse(dialog._installed_elsewhere_label.get_visible())
        self.window.applications = [chrome()]
        self.window._render_store_results([target])
        self.assertTrue(dialog._installed_elsewhere_label.get_visible())
        self.assertIn("APT", dialog._installed_elsewhere_label.get_text())
        self.assertTrue(dialog._switch_btn.get_visible())

    def test_cross_source_installed_badge_and_installed_filter(self):
        from tests.test_source_switch import chrome
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        self.window.applications = [chrome()]
        self.window.store_results = [target]
        self.assertFalse(self.window._store_result_is_installed(target))
        self.assertIn("APT", self.window._store_installed_label(target))
        self.window.store_installed_only = True
        self.window._render_store_results([target])
        self.assertEqual(len(self.window.store_cards.get_children()), 1)

    def test_cancelling_source_switch_confirmation_never_installs_or_removes(self):
        from tests.test_source_switch import chrome
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        with patch.object(Gtk.Dialog, "run", return_value=Gtk.ResponseType.CANCEL), patch.object(self.window, "_run_store_install") as install:
            self.window._confirm_store_source_switch(target, [chrome()])
        install.assert_not_called()
        self.registry.remove.assert_not_called()

    def test_confirmed_source_switch_carries_only_selected_old_installation(self):
        from tests.test_source_switch import chrome
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        old = chrome()
        with patch.object(Gtk.Dialog, "run", return_value=Gtk.ResponseType.OK), patch.object(self.window, "_run_store_install") as install:
            self.window._confirm_store_source_switch(target, [old])
        self.assertEqual(install.call_args.args, (target,))
        self.assertEqual(install.call_args.kwargs["source_switch"].previous, old)
        self.registry.remove.assert_not_called()

    def test_store_source_switch_only_continues_after_verified_success(self):
        from tests.test_source_switch import chrome
        from sourcedock.backend.source_switch import SourceSwitchPlan
        from sourcedock.core.errors import BackendError
        from sourcedock.ui.components.progress import OperationProgressWindow
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        plan = SourceSwitchPlan(target, chrome())
        for scenario in ("ok", "install-failed", "verification-failed", "cancelled", "lingering"):
            with self.subTest(scenario=scenario):
                self.store.install.side_effect = BackendError("failed") if scenario in ("install-failed", "lingering") else None
                self.store.runner.operation_status.return_value = {"cancel_requested": scenario == "cancelled"}
                context = MagicMock()
                context.lingering = scenario == "lingering"
                context.completed_event.wait.return_value = True
                context.returncode = 0
                self.store.runner.get_operation_context.return_value = context
                self.registry.load_sources.return_value = ApplicationSnapshot(
                    [] if scenario == "verification-failed" else [chrome("flatpak", "com.google.Chrome", "/var/lib/flatpak/app/com.google.Chrome")])
                with (patch("sourcedock.ui.views.store_view.threading.Thread") as thread,
                      patch("sourcedock.ui.views.store_view.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)),
                      patch.object(self.window, "_finish_store_install") as finish,
                      patch.object(self.window, "_unregister_active_op"),
                      patch.object(self.window, "_start_source_switch_cleanup") as cleanup):
                    self.window._run_store_install(target, source_switch=plan)
                    thread.call_args.kwargs["target"]()
                if scenario in ("ok", "lingering"):
                    cleanup.assert_called_once_with(plan)
                    self.assertTrue(finish.call_args.args[0])
                else:
                    cleanup.assert_not_called()
                    if scenario != "cancelled":
                        self.assertFalse(finish.call_args.args[0])
                self.registry.remove.assert_not_called()
                for window in Gtk.Window.list_toplevels():
                    if isinstance(window, OperationProgressWindow):
                        window.destroy()

    def test_store_auth_and_classic_retry_preserve_the_source_switch_plan(self):
        from tests.test_source_switch import chrome
        from sourcedock.backend.source_switch import SourceSwitchPlan
        from sourcedock.core.errors import AuthRequiredError
        target = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "2", "flathub")
        plan = SourceSwitchPlan(target, chrome())
        with (patch.object(self.window, "_ask_sudo_password", return_value="fixture-secret"),
              patch.object(self.window, "_run_store_install") as install):
            self.window._handle_store_auth_required(target, AuthRequiredError("auth"), False, source_switch=plan)
            self.assertIs(install.call_args.kwargs["source_switch"], plan)
        with (patch("sourcedock.ui.views.store_view.show_snap_classic_dialog", return_value=True),
              patch.object(self.window, "_run_store_install") as install):
            self.window._handle_snap_classic_required(target, source_switch=plan)
            self.assertIs(install.call_args.kwargs["source_switch"], plan)
            self.assertTrue(install.call_args.kwargs["classic"])


    def test_snap_timeout_with_no_results_never_displays_raw_command(self):
        self.store.last_search_source_states = {SOURCE_APT: "live", SOURCE_FLATPAK: "live", SOURCE_SNAP: "unavailable"}
        self.store.last_search_metrics = {"timed_out_sources": [SOURCE_SNAP]}
        raw = "SNAP: Komut calistirilamadi: snap find google chrome\nCommand '['snap', 'find', 'google chrome']' timed out after 2.0 seconds"
        self.window._finish_store_search([], raw)
        text = self.window.store_status.get_text() + self.window.store_state.body.get_text()
        self.assertNotIn("Command", text)
        self.assertNotIn("snap find", text)
        self.assertNotIn("2.0 seconds", text)
        self.assertIn("Snap", text)
        self.assertTrue(self.window.store_state.retry_button.get_visible())
        self.assertNotEqual(self.window.store_state.title.get_text(), t("tr", "store_no_results"))

    def test_late_provider_failure_keeps_current_partial_results_but_not_previous_queries(self):
        result = StoreResult("Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "1", "flathub")
        self.window._store_search_generation = 3
        self.window._finish_store_search([result], None, generation=3, complete=False)
        self.window._finish_store_search([], "Snap timed out", generation=3)
        self.assertEqual(self.window.store_results, [result])
        self.assertEqual(self.window.store_state.get_visible_child_name(), "content")
        self.window._store_search_generation = 4
        self.window._finish_store_search([], "Snap timed out", generation=4)
        self.assertEqual(self.window.store_results, [])
        self.assertEqual(self.window.store_state.get_visible_child_name(), "state")

    def test_search_during_update_does_not_invalidate_inventory_reconciliation(self):
        self.window._quiet_refresh_generation = 42
        self.window.applications_busy = True
        self.window.header_search.set_text("google chrome")
        with patch("sourcedock.ui.views.store_view.threading.Thread") as thread:
            self.window.on_store_search()
        thread.assert_called_once()
        self.assertEqual(self.window._quiet_refresh_generation, 42)
        self.assertTrue(self.window.store_search_entry.get_sensitive())

    def test_search_callback_uses_captured_provider_diagnostics(self):
        self.window.header_search.set_text("chrome")
        captured = []
        result = StoreResult("Google Chrome", "com.google.Chrome", "", SOURCE_FLATPAK, "1", "flathub")
        def search(_query, sources=None, on_partial=None):
            self.store.last_search_source_states = {SOURCE_FLATPAK: "live", SOURCE_SNAP: "unavailable"}
            self.store.last_search_metrics = {"timed_out_sources": [SOURCE_SNAP]}
            on_partial([result], True)
            self.store.last_search_source_states = {SOURCE_APT: "live"}
            self.store.last_search_metrics = {}
            return [result]
        self.store.search.side_effect = search
        with patch("sourcedock.ui.views.store_view.threading.Thread") as thread, patch(
            "sourcedock.ui.views.store_view.GLib.idle_add", side_effect=lambda *args: captured.append(args)):
            self.window.on_store_search()
            thread.call_args.kwargs["target"]()
        for callback, *args in captured:
            callback(*args)
        self.assertIn("Snap", self.window.store_status.get_text())
        self.assertNotIn("APT", self.window.store_status.get_text())


if __name__ == "__main__":
    unittest.main()
