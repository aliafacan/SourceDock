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
        self.assertEqual(self.window.store_state.body.get_text(), "Provider offline")

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

    def test_partial_update_retry_does_not_repeat_completed_targets(self):
        from sourcedock.core.errors import BackendError

        self.window._finish_updates_load(self._updates(), [], None)
        self.window.updates_select_all_btn.set_active(True)
        with patch.object(self.window, "_confirm_firmware_update", return_value=True), patch.object(self.window, "_run_application_task") as start:
            self.window._on_apply_updates(None)
        worker = start.call_args.args[1]

        def update(app):
            if app.package_name == "org.example.Platform":
                raise BackendError("runtime update failed")

        self.registry.update.side_effect = update
        with patch("sourcedock.ui.views.updates_view.GLib.idle_add"), self.assertRaises(BackendError) as error:
            worker()
        self.assertIn("Runtime", str(error.exception))
        self.assertEqual(self.registry.update.call_count, 4)
        self.registry.update.reset_mock(side_effect=True)
        with patch("sourcedock.ui.views.updates_view.GLib.idle_add"):
            worker()
        self.registry.update.assert_called_once()
        self.assertEqual(self.registry.update.call_args.args[0].package_name, "org.example.Platform")

    def test_cleanup_cancel_never_starts_an_operation(self):
        from sourcedock.backend.flatpak_cleanup import CleanupRef

        with patch("sourcedock.ui.views.installed_view.Gtk.Dialog.run", return_value=Gtk.ResponseType.CANCEL), patch.object(self.window, "_run_application_task") as run:
            self.window._show_flatpak_cleanup_plan(
                (CleanupRef("user", "runtime/org.example.Runtime/x86_64/stable"),), None,
            )
        run.assert_not_called()
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

    def test_installer_auth_retry_starts_a_new_attempt(self):
        info = LocalPackageInfo("/tmp/test.deb", "deb", "Test", version="1")
        dialog = PackageInstallerDialog(parent=self.window, info=info, registry=self.registry)
        self.addCleanup(dialog.destroy)
        dialog._is_installing = True

        def accept_password(auth_dialog):
            for child in auth_dialog.get_content_area().get_children():
                if isinstance(child, Gtk.Entry):
                    child.set_text("test-password")
            return Gtk.ResponseType.OK

        with (
            patch.object(Gtk.Dialog, "run", side_effect=accept_password),
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


if __name__ == "__main__":
    unittest.main()
