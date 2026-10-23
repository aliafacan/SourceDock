#!/usr/bin/env python3
"""SourceDock ana penceresi (MainWindow) ve sekmelerin birleştiricisi."""

from __future__ import annotations

import os
import sys
import threading
import time
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.constants import APP_ICON_NAME, APP_TITLE, APP_VERSION
from sourcedock.core.models import (
    ApplicationIssue,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.update_checker import (
    ReleaseInfo,
    check_latest_release_result,
    download_release_package,
)
from sourcedock.store.registry import StoreRegistry
from sourcedock.i18n import t
from sourcedock.preferences import PreferencesStore
from sourcedock.theme import get_theme_css, resolve_theme, system_reduced_motion
from sourcedock.ui.components.common import icon_button, icon_text_button, prepare_dialog
from sourcedock.ui.views.shell_view import ShellViewMixin
from sourcedock.ui.views.updates_view import UpdatesViewMixin
from sourcedock.ui.views.advanced_view import AdvancedViewMixin

from sourcedock.ui.views.installed_view import InstalledViewMixin
from sourcedock.ui.views.store_view import StoreViewMixin
from sourcedock.ui.views.packages_view import PackagesViewMixin
from sourcedock.ui.views.operations_view import OperationsViewMixin
from sourcedock.ui.views.settings_view import SettingsViewMixin
from sourcedock.ui.views.help_view import HelpViewMixin


class MainWindow(
    Gtk.Window,
    ShellViewMixin,
    UpdatesViewMixin,
    AdvancedViewMixin,
    InstalledViewMixin,
    StoreViewMixin,
    PackagesViewMixin,
    OperationsViewMixin,
    SettingsViewMixin,
    HelpViewMixin,
):
    """SourceDock ana penceresi."""

    def __init__(self, preferences_store: PreferencesStore):
        self.preferences_store = preferences_store
        self.preferences = preferences_store.load()
        super().__init__(title=APP_TITLE)
        self._release_check_destroyed = False
        self._release_check_initial_timer_id = 0
        self._release_check_periodic_timer_id = 0
        self._release_check_in_flight = False
        self._release_check_manual_pending = False
        self._notified_release_version = ""
        self._release_update_in_progress = False

        self.application_registry = ApplicationRegistry()
        self.store_registry = StoreRegistry()

        # Installed apps state
        self.applications: list[UnifiedApplication] = []
        self.application_update_only_items: list[UnifiedApplication] = []
        self.application_issues: list[ApplicationIssue] = []
        self.application_provider_errors: list[str] = []
        self.application_provider_notices: list[str] = []
        self.application_filter_source = "all"
        self.application_filter_category = "__all__"
        self.application_search_text = ""
        self.applications_loading = False
        self.application_updates_loading = False
        self.application_updates_scanned = False
        self._application_update_scan_token = 0
        self._application_initial_load_needs_updates = False
        self.applications_busy = False
        self._cached_sudo_password: str | None = None
        self._cached_sudo_timestamp: float = 0.0
        self.application_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self.filtered_applications: list[UnifiedApplication] = []
        self._suppress_global_search_changed = False

        # Store state
        self.store_results: list[StoreResult] = []
        self.store_filter_source = "all"
        self.store_busy = False
        self._store_search_generation = 0
        # Kept as a compatibility marker for extensions/tests; no debounce
        # source is scheduled anymore.
        self._store_search_timeout_id = 0
        self.store_search_metrics: dict[str, object] = {}
        self.application_load_metrics: dict[str, object] = {}
        self.store_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self.installed_package_ids: set[str] = set()
        self._icon_pixbuf_cache: dict[str, GdkPixbuf.Pixbuf | None] = {}

        # Active operations
        self._active_ops: dict[str, dict] = {}
        self._active_op_seq = 0

        # Packages state
        self.packages: list[PackageInfo] = []
        self.packages_loading = False
        self.packages_search_text = ""
        self.packages_filter_upgradable = False

        self.css_provider = Gtk.CssProvider()
        self.set_default_size(1120, 720)
        self._apply_window_icon()
        self.set_border_width(0)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")
        self.connect("destroy", self._on_window_destroy)

        self._build_ui()
        self._apply_theme()
        self._system_theme_settings = None
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.desktop.interface", True) if source else None
        if schema and schema.has_key("color-scheme"):
            self._system_theme_settings = Gio.Settings.new_full(schema, None, None)
            self._system_theme_settings.connect("changed::color-scheme", self._on_system_theme_changed)
        self._refresh_texts()
        self._setup_keyboard_shortcuts()
        self._setup_drag_and_drop()
        if "--updates" in sys.argv:
            self.pages.set_current_page(4)
        self.reload_applications_async()
        preferred = self.store_filter_buttons.get(self.preferences.preferred_source)
        if preferred:
            preferred.set_active(True)
        if self.preferences.check_updates_on_start:
            self._reload_updates_async()
        if os.environ.get("SOURCEDOCK_DISABLE_RELEASE_CHECK") != "1":
            self._start_release_check()

    def _start_release_check(self) -> None:
        """Check GitHub after startup, then repeat without blocking the UI."""

        self._release_check_initial_timer_id = GLib.timeout_add_seconds(
            20, self._run_initial_release_check
        )

    def _run_initial_release_check(self) -> bool:
        self._release_check_initial_timer_id = 0
        if self._release_check_destroyed:
            return False
        self._run_release_check()
        self._release_check_periodic_timer_id = GLib.timeout_add_seconds(
            6 * 60 * 60, self._run_periodic_release_check
        )
        return False

    def _run_periodic_release_check(self) -> bool:
        if self._release_check_destroyed:
            self._release_check_periodic_timer_id = 0
            return False
        self._run_release_check()
        return True

    def _run_release_check(self, *, manual: bool = False) -> None:
        if self._release_check_destroyed:
            return
        if self._release_check_in_flight:
            if manual:
                self._release_check_manual_pending = True
                self.show_toast(
                    t(self.preferences.language, "app_update_checking"),
                    level="info",
                    timeout=0,
                )
            return
        self._release_check_in_flight = True
        if manual:
            self.show_toast(
                t(self.preferences.language, "app_update_checking"),
                level="info",
                timeout=0,
            )

        def worker() -> None:
            try:
                result = check_latest_release_result(APP_VERSION)
            except Exception:
                result = None
            GLib.idle_add(self._finish_release_check, result, manual)

        threading.Thread(target=worker, daemon=True, name="release-check").start()

    def _finish_release_check(self, result, manual: bool = False) -> bool:
        self._release_check_in_flight = False
        manual = manual or self._release_check_manual_pending
        self._release_check_manual_pending = False
        if self._release_check_destroyed:
            return False
        if result is None:
            if manual:
                message = t(self.preferences.language, "app_update_check_failed")
                self._record_notification(message, "error")
                self.show_toast(message, level="error", timeout=8)
            return False
        release = result.release
        if manual and result.status == "up_to_date":
            message = t(self.preferences.language, "app_update_up_to_date", version=APP_VERSION)
            self._record_notification(message, "success")
            self.show_toast(
                message,
                level="success",
                timeout=6,
            )
        elif manual and result.status == "unavailable":
            message = t(self.preferences.language, "app_update_check_failed")
            self._record_notification(message, "error")
            self.show_toast(message, level="error", timeout=8)
        if release is None:
            return False
        if not manual and release.version == self._notified_release_version:
            return False
        if not manual and not self.preferences.notifications_enabled:
            return False
        self._notified_release_version = release.version
        message = t(self.preferences.language, "app_update_available", version=release.version)
        self._record_notification(message)
        self.show_toast(
            message,
            level="info",
            timeout=10,
            action_label=(
                t(self.preferences.language, "app_update_action")
                if release.deb_url and release.checksum_url
                else None
            ),
            on_action=(lambda: self._start_release_download(release))
            if release.deb_url and release.checksum_url
            else None,
        )
        return False

    def _start_release_download(self, release: ReleaseInfo) -> None:
        """Download a verified DEB, then hand it to the normal installer UI."""

        if self._release_update_in_progress or not release.deb_url or not release.checksum_url:
            return
        self._release_update_in_progress = True
        self.show_toast(
            t(self.preferences.language, "app_update_downloading"),
            level="info",
            timeout=0,
        )

        def worker() -> None:
            try:
                package_path = download_release_package(release)
            except Exception as exc:
                GLib.idle_add(self._finish_release_download, None, str(exc))
            else:
                GLib.idle_add(self._finish_release_download, package_path, None)

        threading.Thread(target=worker, daemon=True, name="release-download").start()

    def _finish_release_download(self, package_path: str | None, error: str | None) -> bool:
        self._release_update_in_progress = False
        if self._release_check_destroyed:
            return False
        if error or not package_path:
            message = t(self.preferences.language, "app_update_download_failed")
            if error:
                message = f"{message}: {error}"
            self._record_notification(message, "error")
            self.show_toast(message, level="error", timeout=10)
            return False
        self.hide_toast()
        self._record_notification(t(self.preferences.language, "app_update_download_ready"), "success")
        self.prompt_and_install_file(package_path, on_finished=self._on_self_update_installed)
        return False

    def _on_self_update_installed(self) -> None:
        self.reload_applications_async()
        message = t(self.preferences.language, "app_update_restart_required")
        self._record_notification(message, "success")
        self.show_toast(
            message,
            level="success",
            timeout=0,
        )

    def _apply_window_icon(self) -> None:
        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(APP_ICON_NAME):
            self.set_icon_name(APP_ICON_NAME)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            for icon_path in (os.path.join(base_dir, "assets", "sourcedock.png"),):
                if os.path.exists(icon_path):
                    try:
                        self.set_icon_from_file(icon_path)
                        break
                    except Exception:
                        pass

    def _build_ui(self) -> None:
        self.pages = Gtk.Notebook()
        self._build_window_shell()

        self.installed_tab_label = Gtk.Label()
        installed_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(installed_page, self.installed_tab_label)

        self.store_tab_label = Gtk.Label()
        store_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(store_page, self.store_tab_label)

        self.packages_tab_label = Gtk.Label()
        packages_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(packages_page, self.packages_tab_label)

        self.operations_tab_label = Gtk.Label(label="İşlemler")
        operations_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(operations_page, self.operations_tab_label)

        self._build_installed_page(installed_page)
        self._build_store_page(store_page)
        self._build_packages_page(packages_page)
        self._build_operations_page(operations_page)
        updates_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.pages.append_page(updates_page, Gtk.Label())
        self._build_updates_page(updates_page)

        self.pages.connect("switch-page", self._on_notebook_switch_page)
        self.pages.set_current_page(0)
        self.show_all()
        self._refresh_shell_texts()

    def _on_notebook_switch_page(self, _notebook: Gtk.Notebook, _page, page_num: int) -> None:
        # GTK emits switch-page before updating get_current_page(). Use the
        # signal's page number so the visible search scope changes atomically.
        self._refresh_shell_page(page_num)
        if page_num == 2 and not self.packages and not self.packages_loading:
            self.reload_packages_async()
        elif page_num == 3:
            self._on_operations_refresh()
        elif page_num == 4 and not self.update_items and not self.updates_loading:
            self._reload_updates_async()

    def _apply_theme(self) -> None:
        scale = getattr(self.preferences, "scale", "100")
        is_dark = resolve_theme(self.preferences.theme) == "dark"

        try:
            default_settings = Gtk.Settings.get_default()
            if default_settings is not None:
                default_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
        except Exception:
            pass

        screen = Gdk.Screen.get_default()
        if screen is not None:
            try:
                screen_settings = Gtk.Settings.get_for_screen(screen)
                if screen_settings is not None:
                    screen_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
            except Exception:
                pass

            self.css_provider.load_from_data(
                get_theme_css(
                    self.preferences.theme, scale, reduced_motion=system_reduced_motion()
                ).encode("utf-8")
            )
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _on_system_theme_changed(self, *_args):
        if self.preferences.theme == "system":
            self._apply_theme()

    def _refresh_texts(self) -> None:
        lang = self.preferences.language
        self.set_title(APP_TITLE)
        self.help_btn.set_tooltip_text(t(lang, "tooltip_help"))
        self.settings_btn.set_tooltip_text(t(lang, "tooltip_settings"))
        self.installed_tab_label.set_text(t(lang, "tab_installed"))
        self.store_tab_label.set_text(t(lang, "tab_store"))
        self.packages_tab_label.set_text(t(lang, "tab_packages"))
        self.operations_tab_label.set_text(t(lang, "tab_operations"))

        # Installed page
        self.applications_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "applications_title")}</span>'
        )
        self.applications_subtitle_label.set_text(t(lang, "applications_subtitle"))
        self.applications_search_entry.set_placeholder_text(t(lang, "applications_search_placeholder"))
        self.applications_search_entry.set_tooltip_text(t(lang, "tooltip_installed_search"))
        self.applications_refresh_btn.set_label(t(lang, "applications_refresh"))
        self.applications_refresh_btn.set_tooltip_text(t(lang, "tooltip_installed_refresh"))
        self.applications_check_updates_btn.set_label(t(lang, "applications_check_updates"))
        self.applications_check_updates_btn.set_tooltip_text(t(lang, "tooltip_installed_check_updates"))
        self.applications_update_all_btn.set_label(t(lang, "applications_update_all"))
        self.applications_update_all_btn.set_tooltip_text(t(lang, "tooltip_installed_update_all"))
        self.applications_tree_col_app.set_title(t(lang, "applications_col_app"))
        self.applications_tree_col_source.set_title(t(lang, "applications_col_source"))
        self.applications_tree_col_version.set_title(t(lang, "applications_col_version"))
        self.applications_tree_col_size.set_title(t(lang, "applications_col_size"))
        if hasattr(self, "applications_tree_col_installed_date"):
            self.applications_tree_col_installed_date.set_title(t(lang, "applications_col_installed_date"))
        if hasattr(self, "applications_tree_col_last_updated"):
            self.applications_tree_col_last_updated.set_title(t(lang, "applications_col_last_updated"))
        self.applications_tree_col_location.set_title(t(lang, "applications_col_location"))
        self.applications_launch_btn.set_label(t(lang, "applications_launch"))
        self.applications_launch_btn.set_tooltip_text(t(lang, "tooltip_installed_launch"))
        if hasattr(self, "applications_details_btn"):
            self.applications_details_btn.set_label(t(lang, "applications_details"))
            self.applications_details_btn.set_tooltip_text(t(lang, "tooltip_installed_details"))
        self.applications_action_update_btn.set_label(t(lang, "applications_update"))
        self.applications_action_update_btn.set_tooltip_text(t(lang, "tooltip_installed_update"))
        self.applications_action_location_btn.set_label(t(lang, "applications_open_location"))
        self.applications_action_location_btn.set_tooltip_text(t(lang, "tooltip_installed_open_location"))
        self.applications_action_remove_btn.set_label(t(lang, "applications_remove"))
        self.applications_action_remove_btn.set_tooltip_text(t(lang, "tooltip_installed_remove"))
        self.applications_bulk_remove_btn.set_label(t(lang, "applications_remove_selected"))
        self.applications_bulk_remove_btn.set_tooltip_text(t(lang, "tooltip_installed_bulk_remove"))
        self.applications_permissions_btn.set_label(t(lang, "flatpak_permissions_btn"))
        self.applications_permissions_btn.set_tooltip_text(t(lang, "tooltip_installed_permissions"))
        self.applications_rollback_btn.set_label(t(lang, "flatpak_rollback_menu"))
        self.applications_rollback_btn.set_tooltip_text(t(lang, "tooltip_installed_rollback"))
        self.applications_changelog_btn.set_label(t(lang, "changelog_menu"))
        self.applications_changelog_btn.set_tooltip_text(t(lang, "tooltip_installed_changelog"))
        self.applications_export_btn.set_label(t(lang, "applications_export"))
        self.applications_export_btn.set_tooltip_text(t(lang, "tooltip_installed_export"))
        if hasattr(self, "applications_install_file_btn"):
            self.applications_install_file_btn.set_label(t(lang, "install_package_btn"))
            self.applications_install_file_btn.set_tooltip_text(t(lang, "tooltip_installed_install_file"))
        self.applications_add_appimage_btn.set_label(t(lang, "appimage_register_btn"))
        self.applications_add_appimage_btn.set_tooltip_text(t(lang, "tooltip_installed_add_appimage"))
        self.applications_export_selected_btn.set_label(t(lang, "export_selected"))
        self.applications_export_selected_btn.set_tooltip_text(t(lang, "tooltip_installed_export_selected"))
        self.applications_more_btn.set_label(t(lang, "applications_more"))
        self.applications_more_btn.set_tooltip_text(t(lang, "applications_more"))
        for attribute, key in (
            ("applications_action_location_btn", "applications_open_location"),
            ("applications_permissions_btn", "flatpak_permissions_btn"),
            ("applications_rollback_btn", "flatpak_rollback_menu"),
            ("applications_changelog_btn", "changelog_menu"),
            ("applications_export_selected_btn", "export_selected"),
            ("applications_export_btn", "applications_export"),
            ("applications_import_btn", "restore_title"),
            ("applications_add_appimage_btn", "appimage_register_btn"),
        ):
            item = self._advanced_action_menu_items.get(attribute)
            if item:
                item.set_label(t(lang, key))
        self.applications_category_label.set_text(t(lang, "applications_category_filter") + ": ")
        if hasattr(self, "applications_category_combo"):
            self.applications_category_combo.set_tooltip_text(t(lang, "tooltip_installed_category"))
        self.applications_diagnostics_expander.set_label(t(lang, "applications_diagnostics"))
        self._render_application_diagnostics()
        self.applications_flatpak_cleanup_btn.set_label(t(lang, "applications_flatpak_cleanup"))
        self.applications_flatpak_cleanup_btn.set_tooltip_text(t(lang, "tooltip_installed_flatpak_cleanup"))

        filter_tooltip_map = {
            "all": "tooltip_installed_filter_all",
            "updates": "tooltip_installed_filter_updates",
            "flatpak": "tooltip_installed_filter_flatpak",
            "snap": "tooltip_installed_filter_snap",
            "appimage": "tooltip_installed_filter_appimage",
            "portable": "tooltip_installed_filter_portable",
            "firmware": "tooltip_installed_filter_firmware",
            "other": "tooltip_installed_filter_other",
        }
        for source, button in self.application_filter_buttons.items():
            button.set_label(self._application_source_label(source))
            tt_key = filter_tooltip_map.get(source, "tooltip_installed_filter_native")
            button.set_tooltip_text(t(lang, tt_key))
        self._update_category_combo()
        if hasattr(self, "applications_layout_toggle"):
            is_grid = self.applications_layout_toggle.get_active()
            icon_button(
                self.applications_layout_toggle,
                "view-list-symbolic" if is_grid else "view-grid-symbolic",
                t(lang, "view_list" if is_grid else "view_grid"),
            )
            self.applications_layout_toggle.set_tooltip_text(t(lang, "tooltip_installed_layout"))
            self.applications_layout_toggle.get_accessible().set_name(t(lang, "tooltip_installed_layout"))
        if hasattr(self, "applications_table_toggle"):
            icon_button(
                self.applications_table_toggle,
                "view-list-symbolic",
                t(lang, "table_details"),
            )
            self.applications_table_toggle.set_tooltip_text(t(lang, "table_details"))

        # Store page

        self.store_title_label.set_markup(f'<span size="large" weight="bold">{t(lang, "store_title")}</span>')
        self.store_subtitle_label.set_text(t(lang, "store_subtitle"))
        self.store_search_entry.set_placeholder_text(t(lang, "store_search_placeholder"))
        self.store_search_entry.set_tooltip_text(t(lang, "tooltip_store_search_entry"))
        self.store_search_btn.set_label(t(lang, "store_search_btn"))
        self.store_search_btn.set_tooltip_text(t(lang, "tooltip_store_search_btn"))
        self.store_install_btn.set_tooltip_text(t(lang, "tooltip_store_install"))
        self.store_tree_col_name.set_title(t(lang, "store_col_name"))
        self.store_tree_col_description.set_title(t(lang, "store_col_description"))
        self.store_tree_col_source.set_title(t(lang, "store_col_source"))
        self.store_tree_col_version.set_title(t(lang, "store_col_version"))
        self.store_tree_col_size.set_title(t(lang, "store_col_size"))

        store_tooltip_map = {
            "all": "tooltip_store_filter_all",
            "flatpak": "tooltip_store_filter_flatpak",
            "snap": "tooltip_store_filter_snap",
        }
        for source, button in self.store_filter_buttons.items():
            label_key = f"store_source_{source}"
            button.set_label(t(lang, label_key))
            stt_key = store_tooltip_map.get(source, "tooltip_store_filter_native")
            button.set_tooltip_text(t(lang, stt_key))
        self._set_store_status(t(lang, "store_empty"), "#666666")
        self.on_store_result_selected(self.store_tree.get_selection())
        self._render_applications_list()

        # Packages page
        native_prov = getattr(self.application_registry, "native_provider", None)
        disp_name = native_prov.display_name if native_prov else "APT"
        self.packages_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "packages_native_title").format(manager=disp_name)}</span>'
        )
        self.packages_subtitle_label.set_text(t(lang, "packages_subtitle"))
        self.packages_search_entry.set_placeholder_text(t(lang, "packages_search_placeholder"))
        self.packages_search_entry.set_tooltip_text(t(lang, "tooltip_packages_search"))
        self.packages_refresh_btn.set_label(t(lang, "packages_refresh"))
        self.packages_refresh_btn.set_tooltip_text(t(lang, "tooltip_packages_refresh"))
        self.packages_filter_all_btn.set_label(t(lang, "packages_filter_all"))
        self.packages_filter_all_btn.set_tooltip_text(t(lang, "tooltip_packages_filter_all"))
        self.packages_filter_upgradable_btn.set_label(t(lang, "packages_filter_upgradable"))
        self.packages_filter_upgradable_btn.set_tooltip_text(t(lang, "tooltip_packages_filter_upgradable"))
        self.packages_tree_col_name.set_title(t(lang, "packages_col_name"))
        self.packages_tree_col_version.set_title(t(lang, "packages_col_version"))
        self.packages_tree_col_new_version.set_title(t(lang, "packages_col_new_version"))
        self.packages_tree_col_size.set_title(t(lang, "packages_col_size"))
        self.packages_tree_col_description.set_title(t(lang, "packages_col_description"))
        self.packages_details_btn.set_label(t(lang, "applications_details"))
        self.packages_details_btn.set_tooltip_text(t(lang, "tooltip_installed_details"))
        self.packages_remove_btn.set_label(t(lang, "applications_remove"))
        self.packages_remove_btn.set_tooltip_text(t(lang, "tooltip_installed_remove"))
        self.packages_update_btn.set_label(t(lang, "packages_update_selected"))
        self.packages_update_btn.set_tooltip_text(t(lang, "tooltip_packages_update_selected"))
        self.packages_update_all_btn.set_label(t(lang, "packages_update_all"))
        self.packages_update_all_btn.set_tooltip_text(t(lang, "tooltip_packages_update_all"))

        # Operations page
        self.operations_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "operations_title")}</span>'
        )
        self.operations_subtitle_label.set_text(t(lang, "operations_subtitle"))
        self.operations_refresh_btn.set_label(t(lang, "operations_refresh"))
        self.operations_refresh_btn.set_tooltip_text(t(lang, "tooltip_operations_refresh"))
        self.operations_pause_btn.set_label(t(lang, "operations_pause"))
        self.operations_pause_btn.set_tooltip_text(t(lang, "tooltip_operations_pause"))
        self.operations_cancel_btn.set_label(t(lang, "operations_cancel"))
        self.operations_cancel_btn.set_tooltip_text(t(lang, "tooltip_operations_cancel"))
        self.operations_tree_col_process.set_title(t(lang, "operations_col_process"))
        self.operations_tree_col_pid.set_title(t(lang, "operations_col_pid"))
        self.operations_tree_col_target.set_title(t(lang, "operations_col_target"))
        self._refresh_history()
        self._refresh_updates_texts()
        self._refresh_shell_texts()
        self._compact_action_buttons()
        for button, key in self.store_category_buttons:
            button.set_label(t(lang, f"category_{key}"))
        icon_button(self.applications_table_toggle, "view-list-symbolic", t(lang, "table_details"))
        icon_button(self.store_layout_toggle, "view-list-symbolic", t(lang, "table_details"))

    def _compact_action_buttons(self):
        lang = self.preferences.language
        for label in (
            self.applications_subtitle_label,
            self.store_subtitle_label,
            self.packages_subtitle_label,
            self.operations_subtitle_label,
        ):
            label.set_no_show_all(True)
            label.hide()
        actions = (
            (self.applications_refresh_btn, "view-refresh-symbolic", "tooltip_installed_refresh"),
            (
                self.applications_check_updates_btn,
                "software-update-available-symbolic",
                "tooltip_installed_check_updates",
            ),
            (self.applications_export_btn, "document-save-symbolic", "tooltip_installed_export"),
            (self.applications_import_btn, "document-open-symbolic", "restore_title"),
            (self.applications_add_appimage_btn, "list-add-symbolic", "tooltip_installed_add_appimage"),
            (self.applications_launch_btn, "media-playback-start-symbolic", "tooltip_installed_launch"),
            (self.applications_details_btn, "document-properties-symbolic", "tooltip_installed_details"),
            (
                self.applications_action_update_btn,
                "software-update-available-symbolic",
                "tooltip_installed_update",
            ),
            (
                self.applications_action_location_btn,
                "folder-open-symbolic",
                "tooltip_installed_open_location",
            ),
            (self.applications_permissions_btn, "changes-prevent-symbolic", "tooltip_installed_permissions"),
            (self.applications_rollback_btn, "edit-undo-symbolic", "tooltip_installed_rollback"),
            (self.applications_changelog_btn, "document-open-recent-symbolic", "tooltip_installed_changelog"),
            (self.applications_action_remove_btn, "user-trash-symbolic", "tooltip_installed_remove"),
            (self.applications_bulk_remove_btn, "edit-delete-symbolic", "tooltip_installed_bulk_remove"),
            (
                self.applications_export_selected_btn,
                "document-save-symbolic",
                "tooltip_installed_export_selected",
            ),
            (self.packages_refresh_btn, "view-refresh-symbolic", "tooltip_packages_refresh"),
        )
        primary_actions = {
            self.applications_launch_btn: "applications_launch",
            self.applications_details_btn: "applications_details",
            self.applications_action_update_btn: "applications_update",
            self.applications_action_remove_btn: "applications_remove",
            self.applications_bulk_remove_btn: "applications_remove_selected",
        }
        for button, icon, key in actions:
            if button in primary_actions:
                label = t(lang, primary_actions[button])
                icon_text_button(button, icon, label, t(lang, key))
            else:
                icon_button(button, icon, t(lang, key))
        for button in (self.applications_install_file_btn, self.applications_update_all_btn):
            button.set_no_show_all(True)
            button.hide()
        for button in (
            self.applications_export_btn,
            self.applications_import_btn,
            self.applications_add_appimage_btn,
        ):
            button.set_no_show_all(True)
            button.hide()

    def _setup_keyboard_shortcuts(self) -> None:
        self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, _window: Gtk.Window, event: Gdk.EventKey) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = Gdk.keyval_name(event.keyval) or ""
        if key == "F1":
            self.on_open_help(None)
            return True
        if ctrl and key.lower() in ("f", "k"):
            self.header_search.grab_focus()
            return True
        if key == "Escape":
            self.header_search.set_text("")
            return True
        if ctrl and key.lower() == "l":
            self.on_install_local_package(None)
            return True
        if key == "F5":
            page = self.pages.get_current_page()
            if page == 0:
                self.reload_applications_async()
            elif page == 2:
                self.reload_packages_async()
            elif page == 4:
                self._reload_updates_async()
            return True
        return False

    def _setup_drag_and_drop(self) -> None:
        self.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY,
        )
        self.connect("drag-data-received", self._on_window_drag_data_received)

    def _on_window_drag_data_received(self, _widget, drag_context, _x, _y, data, _info, time) -> None:
        target_file = None
        uris = data.get_uris()
        if not uris:
            text = data.get_text()
            if text:
                uris = [line.strip() for line in text.splitlines() if line.strip()]
        if uris:
            for uri in uris:
                try:
                    filename, _ = GLib.filename_from_uri(uri)
                except Exception:
                    filename = uri.replace("file://", "").strip()
                if os.path.exists(filename):
                    target_file = filename
                    break

        Gtk.drag_finish(drag_context, target_file is not None, False, time)

        if target_file:
            GLib.idle_add(self.prompt_and_install_file, target_file)

    def get_cached_sudo_password(self) -> str | None:
        if not hasattr(self, "_cached_sudo_password") or not self._cached_sudo_password:
            return None
        timestamp = getattr(self, "_cached_sudo_timestamp", 0.0)
        # FIX P1-03: timestamp=0.0 means "not set" → treat as expired, never return stale password.
        # Previously: "timestamp > 0.0 AND elapsed > 900" allowed 0.0 to bypass expiry entirely.
        if not timestamp or time.monotonic() - timestamp > 900:
            self.clear_cached_sudo_password()
            return None
        return self._cached_sudo_password

    def set_cached_sudo_password(self, password: str | None) -> None:
        self._cached_sudo_password = password
        self._cached_sudo_timestamp = time.monotonic() if password else 0.0

    def clear_cached_sudo_password(self) -> None:
        self._cached_sudo_password = None
        self._cached_sudo_timestamp = 0.0
        if hasattr(self, "application_registry") and self.application_registry:
            self.application_registry.runner.clear_sudo_password()
        if hasattr(self, "store_registry") and self.store_registry:
            self.store_registry.clear_sudo_password()

    def _on_window_destroy(self, *_args) -> None:
        self._release_check_destroyed = True
        for attr in ("_release_check_initial_timer_id", "_release_check_periodic_timer_id"):
            source_id = getattr(self, attr, 0)
            if source_id:
                try:
                    GLib.source_remove(source_id)
                except (TypeError, ValueError):
                    pass
                setattr(self, attr, 0)
        self.clear_cached_sudo_password()
        Gtk.main_quit()

    def _ask_sudo_password(
        self,
        retry: bool = False,
        message_key: str = "applications_password_message",
        retry_key: str = "applications_password_retry",
        operation: str = "",
        message: str | None = None,
    ) -> str | None:
        if not retry:
            cached = self.get_cached_sudo_password()
            if cached:
                return cached
        self.clear_cached_sudo_password()

        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "password_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=480, height=220)
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(self.preferences.language, "password_continue"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        message = t(self.preferences.language, retry_key if retry else message_key)
        if operation:
            message = f"{message}\n\n{t(self.preferences.language, 'password_operation', operation=operation)}"
        label = Gtk.Label(label=message)
        label.set_line_wrap(True)
        label.set_xalign(0)
        content.pack_start(label, False, False, 0)

        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_activates_default(True)
        entry.set_placeholder_text(t(self.preferences.language, "password_placeholder"))
        content.pack_start(entry, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        password = entry.get_text()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and password:
            self.set_cached_sudo_password(password)
            return password
        self.clear_cached_sudo_password()
        return None

    def _show_error_dialog(self, message: str) -> None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "dialog_error"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=520, height=220)
        dialog.add_button(t(self.preferences.language, "dialog_close"), Gtk.ResponseType.CLOSE)
        body = Gtk.Label(label=message, xalign=0)
        body.set_line_wrap(True)
        body.set_selectable(True)
        body.get_style_context().add_class("error-text")
        dialog.get_content_area().pack_start(body, True, True, 16)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_export_selected_applications(self, *_args) -> None:
        sel = self.applications_tree.get_selection()
        model, paths = sel.get_selected_rows()
        selected_apps = [model.get_value(model.get_iter(p), 8) for p in paths]
        if not selected_apps:
            return
        import json as _json

        data = [
            {
                "name": a.name,
                "source": a.source,
                "version": a.version,
                "package": a.package_name,
            }
            for a in selected_apps
        ]
        dialog = Gtk.FileChooserDialog(
            title=t(self.preferences.language, "export_dialog_title"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            t(self.preferences.language, "password_cancel"),
            Gtk.ResponseType.CANCEL,
            t(self.preferences.language, "settings_save"),
            Gtk.ResponseType.OK,
        )
        dialog.set_current_name("selected_applications.json")
        if dialog.run() == Gtk.ResponseType.OK:
            fname = dialog.get_filename()
            if fname:
                with open(fname, "w", encoding="utf-8") as fh:
                    _json.dump(data, fh, indent=2, ensure_ascii=False)
                self._set_applications_status(f"Dışa aktarıldı: {fname}", "#1f7a1f")
        dialog.destroy()


def main() -> None:
    """SourceDock uygulamasını başlatan giriş noktası."""
    store = PreferencesStore()
    window = MainWindow(store)
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
