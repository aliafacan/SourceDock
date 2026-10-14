#!/usr/bin/env python3
"""SourceDock ana penceresi (MainWindow) ve sekmelerin birleştiricisi."""

from __future__ import annotations

import os
import sys
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.constants import APP_ICON_NAME, APP_TITLE
from sourcedock.core.models import (
    ApplicationIssue,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.store.registry import StoreRegistry
from sourcedock.i18n import t
from sourcedock.preferences import PreferencesStore
from sourcedock.theme import get_theme_css, resolve_theme
from sourcedock.ui.components.common import icon_button
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

        self.application_registry = ApplicationRegistry()
        self.store_registry = StoreRegistry()

        # Installed apps state
        self.applications: list[UnifiedApplication] = []
        self.application_issues: list[ApplicationIssue] = []
        self.application_provider_errors: list[str] = []
        self.application_filter_source = "all"
        self.application_filter_category = "__all__"
        self.application_search_text = ""
        self.applications_loading = False
        self.applications_busy = False
        self.application_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self.filtered_applications: list[UnifiedApplication] = []

        # Store state
        self.store_results: list[StoreResult] = []
        self.store_filter_source = "all"
        self.store_busy = False
        self._store_search_generation = 0
        self._store_search_timeout_id = 0
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
        self.connect("destroy", Gtk.main_quit)

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
        GLib.idle_add(self._refresh_shell_page)
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

            self.css_provider.load_from_data(get_theme_css(self.preferences.theme, scale).encode("utf-8"))
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
        self.applications_bulk_remove_btn.set_label(t(lang, "applications_remove") + " (×N)")
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
        self.applications_category_label.set_text(t(lang, "applications_category_filter") + ": ")
        if hasattr(self, "applications_category_combo"):
            self.applications_category_combo.set_tooltip_text(t(lang, "tooltip_installed_category"))
        self.applications_diagnostics_expander.set_label(t(lang, "applications_diagnostics"))
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
        }
        for source, button in self.application_filter_buttons.items():
            button.set_label(self._application_source_label(source))
            tt_key = filter_tooltip_map.get(source, "tooltip_installed_filter_native")
            button.set_tooltip_text(t(lang, tt_key))
        self._update_category_combo()

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
        for button, icon, key in actions:
            icon_button(button, icon, t(lang, key))
        for button in (self.applications_install_file_btn, self.applications_update_all_btn):
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

    def _ask_sudo_password(
        self,
        retry: bool = False,
        message_key: str = "applications_password_message",
        retry_key: str = "applications_password_retry",
    ) -> str | None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "password_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.get_style_context().add_class("icon-settings-window")
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
        return password if response == Gtk.ResponseType.OK else None

    def _show_error_dialog(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Hata",
        )
        dialog.get_style_context().add_class("icon-settings-window")
        dialog.format_secondary_text(message)
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
