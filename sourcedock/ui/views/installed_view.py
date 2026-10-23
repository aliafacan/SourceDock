#!/usr/bin/env python3
"""Yüklü uygulamalar görünümü ve aksiyonları (InstalledViewMixin)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import os
from pathlib import Path
import threading
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.icons import find_flatpak_icon_path
from sourcedock.backend.flatpak_cleanup import apply_cleanup, plan_cleanup
from sourcedock.core.models import (
    NATIVE_SOURCES,
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_FLATPAK,
    SOURCE_PACMAN,
    SOURCE_PORTABLE,
    SOURCE_SNAP,
    SOURCE_ZYPPER,
    SOURCE_FIRMWARE,
    ApplicationIssue,
    ApplicationSnapshot,
    UnifiedApplication,
    is_native_source,
)
from sourcedock.i18n import source_name, t, translate_backend_message, translate_provider_error, translate_provider_notice
from sourcedock.ui.components.progress import OperationProgressWindow
from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog
from sourcedock.ui.components.removal import add_sensitive_removal_confirmation
from sourcedock.ui.components.common import (
    ContentState,
    icon_button,
    load_dialog_data,
    make_window_movable,
    prepare_dialog,
    set_status,
    style_tree_view,
)

_AC_ICON = 0
_AC_NAME = 1
_AC_SOURCE = 2
_AC_VERSION = 3
_AC_SIZE_KIB = 4
_AC_SIZE_STR = 5
_AC_INSTALLED_DATE = 6
_AC_LAST_UPDATED = 7
_AC_LOCATION = 8
_AC_APP = 9


class InstalledAppCard(Gtk.Button):
    """Card widget for an installed application in grid mode."""

    def __init__(self, application: UnifiedApplication, pixbuf, on_details, language: str) -> None:
        super().__init__()
        self.get_style_context().add_class("app-card")
        self.set_size_request(240, 160)
        self.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(spacing=10)
        image = (
            Gtk.Image.new_from_pixbuf(pixbuf)
            if pixbuf
            else Gtk.Image.new_from_icon_name("package-x-generic", Gtk.IconSize.DIALOG)
        )
        image.set_pixel_size(48)
        header.pack_start(image, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name = Gtk.Label(label=application.name, xalign=0)
        name.set_line_wrap(True)
        name.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        name.set_max_width_chars(24)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_lines(2)
        name.get_style_context().add_class("app-name")
        title_box.pack_start(name, False, False, 0)

        sub_label = application.version or application.package_name or ""
        if sub_label:
            ver = Gtk.Label(label=sub_label, xalign=0)
            ver.set_ellipsize(Pango.EllipsizeMode.END)
            ver.set_max_width_chars(24)
            ver.get_style_context().add_class("dim-label")
            title_box.pack_start(ver, False, False, 0)
        header.pack_start(title_box, True, True, 0)
        box.pack_start(header, False, False, 0)

        meta_row = Gtk.Box(spacing=6)
        src_lbl = source_name(language, application.source)
        source = Gtk.Label(label=src_lbl, xalign=0)
        source.get_style_context().add_class("source-badge")
        meta_row.pack_start(source, False, False, 0)

        size_kib = application.installed_size_kib
        if size_kib:
            size_str = (
                f"{size_kib / (1024 * 1024):.1f} GB"
                if size_kib >= 1024 * 1024
                else f"{size_kib / 1024:.1f} MB"
                if size_kib >= 1024
                else f"{size_kib} KB"
            )
            size_label = Gtk.Label(label=size_str, xalign=0)
            size_label.get_style_context().add_class("dim-label")
            meta_row.pack_start(size_label, False, False, 0)
        box.pack_start(meta_row, False, False, 0)

        box.pack_start(Gtk.Box(), True, True, 0)

        footer = Gtk.Box(spacing=8)
        footer.pack_start(Gtk.Box(), True, True, 0)
        action_label = Gtk.Label(label=t(language, "applications_details"))
        action_label.get_style_context().add_class("card-action")
        footer.pack_end(action_label, False, False, 0)
        footer.pack_end(
            Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON),
            False,
            False,
            0,
        )
        box.pack_end(footer, False, False, 0)

        self.add(box)
        self.set_tooltip_text(f"{application.name} ({src_lbl}) — {t(language, 'applications_details')}")
        self.get_accessible().set_name(f"{application.name}, {src_lbl}")
        self.connect("clicked", lambda _btn: on_details(application))


class InstalledViewMixin:

    """Yüklü uygulamalar sayfası arayüz kurulumu ve işlem metotları."""

    def _build_installed_page(self, container: Gtk.Box) -> None:
        self.applications_title_label = Gtk.Label()
        self.applications_title_label.set_xalign(0)
        container.pack_start(self.applications_title_label, False, False, 0)

        self.applications_subtitle_label = Gtk.Label()
        self.applications_subtitle_label.set_xalign(0)
        self.applications_subtitle_label.set_line_wrap(True)
        self.applications_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.applications_subtitle_label, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        container.pack_start(toolbar, False, False, 0)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.pack_start(search_row, False, False, 0)

        self.applications_search_entry = Gtk.SearchEntry()
        self.applications_search_entry.set_hexpand(True)
        self.applications_search_entry.connect("search-changed", self.on_applications_search_changed)
        self.applications_search_entry.set_no_show_all(True)
        self.applications_search_entry.hide()
        search_row.pack_start(self.applications_search_entry, True, True, 0)

        self.applications_refresh_btn = Gtk.Button()
        self.applications_refresh_btn.connect("clicked", self.on_reload_applications)
        search_row.pack_start(self.applications_refresh_btn, False, False, 0)

        self.applications_check_updates_btn = Gtk.Button()
        self.applications_check_updates_btn.connect("clicked", self.on_check_for_updates)
        search_row.pack_start(self.applications_check_updates_btn, False, False, 0)

        self.applications_update_all_btn = Gtk.Button()
        self.applications_update_all_btn.get_style_context().add_class("suggested-action")
        self.applications_update_all_btn.connect("clicked", self.on_update_all_applications)
        search_row.pack_start(self.applications_update_all_btn, False, False, 0)

        self.applications_export_btn = Gtk.Button()
        self.applications_export_btn.connect("clicked", self.on_export_application_list)
        search_row.pack_start(self.applications_export_btn, False, False, 0)
        self.applications_import_btn = Gtk.Button()
        self.applications_import_btn.connect("clicked", self.on_import_application_list)
        search_row.pack_start(self.applications_import_btn, False, False, 0)

        self.applications_install_file_btn = Gtk.Button()
        self.applications_install_file_btn.connect("clicked", self.on_install_local_package)
        self.applications_install_file_btn.get_style_context().add_class("suggested-action")
        search_row.pack_start(self.applications_install_file_btn, False, False, 0)

        self.applications_add_appimage_btn = Gtk.Button()
        self.applications_add_appimage_btn.connect("clicked", self.on_add_appimage)
        search_row.pack_start(self.applications_add_appimage_btn, False, False, 0)

        filter_outer = Gtk.FlowBox()
        filter_outer.set_selection_mode(Gtk.SelectionMode.NONE)
        filter_outer.set_min_children_per_line(1)
        filter_outer.set_max_children_per_line(10)
        filter_outer.set_column_spacing(4)
        filter_outer.set_row_spacing(4)
        filter_outer.set_valign(Gtk.Align.CENTER)
        toolbar.pack_start(filter_outer, False, False, 0)

        native_provider = getattr(self.application_registry, "native_provider", None)
        native_key = native_provider.source if native_provider else SOURCE_APT
        source_filters = [
            "all",
            "updates",
            native_key,
            SOURCE_FLATPAK,
            SOURCE_SNAP,
            "other",
        ]
        for source in source_filters:
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_application_filter_toggled, source)
            filter_outer.add(button)
            self.application_filter_buttons[source] = button

        category_row = Gtk.Box(spacing=8)
        toolbar.pack_start(category_row, False, False, 0)
        self.applications_category_label = Gtk.Label()
        self.applications_category_label.set_valign(Gtk.Align.CENTER)
        self.applications_category_label.get_style_context().add_class("dim-label")
        category_row.pack_start(self.applications_category_label, False, False, 0)

        self.applications_category_combo = Gtk.ComboBoxText()
        self.applications_category_combo.set_valign(Gtk.Align.CENTER)
        self.applications_category_combo.set_size_request(150, -1)
        self.applications_category_combo.append("__all__", "")
        self.applications_category_combo.connect("changed", self._on_category_filter_changed)
        category_row.pack_start(self.applications_category_combo, False, False, 0)

        self.applications_summary_label = Gtk.Label()
        self.applications_summary_label.set_xalign(0)
        self.applications_summary_label.get_style_context().add_class("dim-label")
        container.pack_start(self.applications_summary_label, False, False, 0)

        self.applications_store = Gtk.ListStore(
            GdkPixbuf.Pixbuf,
            str,
            str,
            str,
            int,
            str,
            str,
            str,
            str,
            GObject.TYPE_PYOBJECT,
        )
        self.applications_tree = Gtk.TreeView(model=self.applications_store)
        style_tree_view(self.applications_tree)
        self.applications_tree.set_headers_visible(True)
        self.applications_tree.set_activate_on_single_click(False)
        self.applications_tree.set_enable_search(False)
        self.applications_tree.set_rubber_banding(False)
        self.applications_tree.set_has_tooltip(True)
        self.applications_tree.get_style_context().add_class("applications-tree")
        self.applications_tree.connect("row-activated", self.on_application_tree_activated)
        self.applications_tree.connect("button-press-event", self.on_application_tree_button_press)
        self.applications_tree.connect("key-press-event", self.on_applications_tree_key_press)
        self.applications_tree.connect("query-tooltip", self.on_applications_tree_query_tooltip)

        selection = self.applications_tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.connect("changed", self.on_application_selection_changed)

        app_col = Gtk.TreeViewColumn()
        self.applications_tree_col_app = app_col
        icon_renderer = Gtk.CellRendererPixbuf()
        icon_renderer.set_property("xpad", 4)
        name_renderer = Gtk.CellRendererText()
        name_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        app_col.pack_start(icon_renderer, False)
        app_col.pack_start(name_renderer, True)
        app_col.add_attribute(icon_renderer, "pixbuf", _AC_ICON)
        app_col.add_attribute(name_renderer, "text", _AC_NAME)
        app_col.set_sort_column_id(_AC_NAME)
        app_col.set_resizable(True)
        app_col.set_expand(True)
        app_col.set_min_width(180)
        self.applications_tree.append_column(app_col)

        source_renderer = Gtk.CellRendererText()
        source_col = Gtk.TreeViewColumn()
        self.applications_tree_col_source = source_col
        source_col.pack_start(source_renderer, True)
        source_col.add_attribute(source_renderer, "text", _AC_SOURCE)
        source_col.set_sort_column_id(_AC_SOURCE)
        source_col.set_resizable(True)
        source_col.set_fixed_width(90)
        self.applications_tree.append_column(source_col)

        version_renderer = Gtk.CellRendererText()
        version_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        version_col = Gtk.TreeViewColumn()
        self.applications_tree_col_version = version_col
        version_col.pack_start(version_renderer, True)
        version_col.add_attribute(version_renderer, "text", _AC_VERSION)
        version_col.set_sort_column_id(_AC_VERSION)
        version_col.set_resizable(True)
        version_col.set_fixed_width(140)
        version_col.set_min_width(120)
        self.applications_tree.append_column(version_col)

        size_renderer = Gtk.CellRendererText()
        size_col = Gtk.TreeViewColumn()
        self.applications_tree_col_size = size_col
        size_col.pack_start(size_renderer, True)
        size_col.add_attribute(size_renderer, "text", _AC_SIZE_STR)
        size_col.set_sort_column_id(_AC_SIZE_KIB)
        size_col.set_resizable(True)
        size_col.set_fixed_width(90)
        self.applications_tree.append_column(size_col)

        inst_date_renderer = Gtk.CellRendererText()
        inst_date_col = Gtk.TreeViewColumn()
        self.applications_tree_col_installed_date = inst_date_col
        self.applications_tree_col_date = inst_date_col
        inst_date_col.pack_start(inst_date_renderer, True)
        inst_date_col.add_attribute(inst_date_renderer, "text", _AC_INSTALLED_DATE)
        inst_date_col.set_sort_column_id(_AC_INSTALLED_DATE)
        inst_date_col.set_resizable(True)
        inst_date_col.set_fixed_width(145)
        inst_date_col.set_min_width(135)
        self.applications_tree.append_column(inst_date_col)

        last_upd_renderer = Gtk.CellRendererText()
        last_upd_col = Gtk.TreeViewColumn()
        self.applications_tree_col_last_updated = last_upd_col
        last_upd_col.pack_start(last_upd_renderer, True)
        last_upd_col.add_attribute(last_upd_renderer, "text", _AC_LAST_UPDATED)
        last_upd_col.set_sort_column_id(_AC_LAST_UPDATED)
        last_upd_col.set_resizable(True)
        last_upd_col.set_fixed_width(145)
        last_upd_col.set_min_width(135)
        self.applications_tree.append_column(last_upd_col)

        location_renderer = Gtk.CellRendererText()
        location_renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        location_col = Gtk.TreeViewColumn()
        self.applications_tree_col_location = location_col
        location_col.pack_start(location_renderer, True)
        location_col.add_attribute(location_renderer, "text", _AC_LOCATION)
        location_col.set_sort_column_id(_AC_LOCATION)
        location_col.set_resizable(True)
        location_col.set_expand(True)
        location_col.set_min_width(120)
        self.applications_tree.append_column(location_col)
        detailed_default = getattr(self.preferences, "detailed_table_default", True)
        for column in (inst_date_col, last_upd_col, location_col):
            column.set_visible(detailed_default)
        self.applications_table_toggle = Gtk.ToggleButton()
        self.applications_table_toggle.set_active(detailed_default)
        icon_button(
            self.applications_table_toggle,
            "view-list-symbolic",
            t(self.preferences.language, "table_details"),
        )
        self.applications_table_toggle.connect(
            "toggled",
            lambda button: [
                column.set_visible(button.get_active())
                for column in (inst_date_col, last_upd_col, location_col)
            ],
        )
        search_row.pack_end(self.applications_table_toggle, False, False, 0)

        self.applications_layout_toggle = Gtk.ToggleButton()
        icon_button(
            self.applications_layout_toggle,
            "view-grid-symbolic",
            t(self.preferences.language, "view_grid"),
        )
        self.applications_layout_toggle.set_tooltip_text(
            t(self.preferences.language, "tooltip_installed_layout")
        )
        self.applications_layout_toggle.get_accessible().set_name(
            t(self.preferences.language, "tooltip_installed_layout")
        )
        self.applications_layout_toggle.connect("toggled", self._on_applications_layout_toggled)
        search_row.pack_end(self.applications_layout_toggle, False, False, 0)

        apps_scroller = Gtk.ScrolledWindow()
        apps_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        apps_scroller.add(self.applications_tree)
        self.apps_scroller = apps_scroller

        self.applications_cards = Gtk.FlowBox()
        self.applications_cards.set_selection_mode(Gtk.SelectionMode.NONE)
        self.applications_cards.set_homogeneous(True)
        self.applications_cards.set_min_children_per_line(1)
        self.applications_cards.set_max_children_per_line(3)
        self.applications_cards.set_column_spacing(12)
        self.applications_cards.set_row_spacing(12)
        self.applications_cards.set_valign(Gtk.Align.START)
        cards_scroll = Gtk.ScrolledWindow()
        cards_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        cards_scroll.add(self.applications_cards)
        self.cards_scroll = cards_scroll

        self.applications_view_stack = Gtk.Stack()
        self.applications_view_stack.add_named(apps_scroller, "table")
        self.applications_view_stack.add_named(cards_scroll, "cards")

        self.installed_state = ContentState(self.applications_view_stack)
        container.pack_start(self.installed_state, True, True, 0)


        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.applications_launch_btn = Gtk.Button()
        self.applications_launch_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_launch_application)
        )
        action_bar.pack_start(self.applications_launch_btn, False, False, 0)

        self.applications_details_btn = Gtk.Button()
        self.applications_details_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_show_application_details)
        )
        action_bar.pack_start(self.applications_details_btn, False, False, 0)

        self.applications_action_update_btn = Gtk.Button()
        self.applications_action_update_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_update_application)
        )
        action_bar.pack_start(self.applications_action_update_btn, False, False, 0)

        self.applications_action_location_btn = Gtk.Button()
        self.applications_action_location_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_open_application_location)
        )

        self.applications_permissions_btn = Gtk.Button()
        self.applications_permissions_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_permissions)
        )

        self.applications_rollback_btn = Gtk.Button()
        self.applications_rollback_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_rollback)
        )

        self.applications_changelog_btn = Gtk.Button()
        self.applications_changelog_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_show_changelog)
        )

        self.applications_action_remove_btn = Gtk.Button()
        self.applications_action_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_action_remove_btn.connect(
            "clicked", lambda _b: self._on_selected_app_action(self.on_remove_application)
        )
        action_bar.pack_start(self.applications_action_remove_btn, False, False, 0)

        self.applications_bulk_remove_btn = Gtk.Button()
        self.applications_bulk_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_bulk_remove_btn.connect("clicked", self.on_bulk_remove_applications)
        action_bar.pack_start(self.applications_bulk_remove_btn, False, False, 0)

        self.applications_export_selected_btn = Gtk.Button()
        self.applications_export_selected_btn.connect("clicked", self._on_export_selected_applications)
        self.applications_export_selected_btn.set_sensitive(False)

        self.applications_more_btn = Gtk.MenuButton(label=t(self.preferences.language, "applications_more"))
        self.applications_more_btn.set_tooltip_text(t(self.preferences.language, "applications_more"))
        more_menu = Gtk.Menu()
        self._advanced_action_menu_items = {}
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
            item = Gtk.MenuItem(label=t(self.preferences.language, key))
            item.connect("activate", lambda _item, name=attribute: getattr(self, name).clicked())
            more_menu.append(item)
            self._advanced_action_menu_items[attribute] = item
        more_menu.show_all()
        self.applications_more_btn.set_popup(more_menu)
        action_bar.pack_start(self.applications_more_btn, False, False, 0)

        for btn in (
            self.applications_launch_btn,
            self.applications_details_btn,
            self.applications_action_update_btn,
            self.applications_action_location_btn,
            self.applications_action_remove_btn,
            self.applications_permissions_btn,
            self.applications_rollback_btn,
            self.applications_changelog_btn,
            self.applications_bulk_remove_btn,
        ):
            btn.set_sensitive(False)

        self.applications_diagnostics_expander = Gtk.Expander()
        self.applications_diagnostics_expander.get_style_context().add_class("diagnostics-expander")
        diagnostics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        diagnostics_box.set_border_width(8)
        self.applications_diagnostics_label = Gtk.Label()
        self.applications_diagnostics_label.set_xalign(0)
        self.applications_diagnostics_label.set_line_wrap(True)
        self.applications_diagnostics_label.get_style_context().add_class("dim-label")
        diagnostics_box.pack_start(self.applications_diagnostics_label, False, False, 0)
        self.applications_diagnostics_list = Gtk.ListBox()
        self.applications_diagnostics_list.get_style_context().add_class("diagnostics-list")
        self.applications_diagnostics_list.set_selection_mode(Gtk.SelectionMode.NONE)
        diagnostics_box.pack_start(self.applications_diagnostics_list, False, False, 0)

        maintenance_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        maintenance_row.set_margin_top(4)
        self.applications_flatpak_cleanup_btn = Gtk.Button()
        self.applications_flatpak_cleanup_btn.connect("clicked", self.on_flatpak_cleanup)
        maintenance_row.pack_start(self.applications_flatpak_cleanup_btn, False, False, 0)
        diagnostics_box.pack_start(maintenance_row, False, False, 0)

        self.applications_diagnostics_expander.add(diagnostics_box)
        container.pack_start(self.applications_diagnostics_expander, False, False, 0)

        self.applications_status = Gtk.Label()
        self.applications_status.set_xalign(0)
        self.applications_status.set_line_wrap(True)
        container.pack_start(self.applications_status, False, False, 0)

        self.application_filter_buttons["all"].set_active(True)
        self.applications_category_combo.set_active(0)

    def _on_applications_layout_toggled(self, button: Gtk.ToggleButton) -> None:
        is_grid = button.get_active()
        self.applications_view_stack.set_visible_child_name("cards" if is_grid else "table")
        self.applications_table_toggle.set_sensitive(not is_grid)
        icon_button(
            button,
            "view-list-symbolic" if is_grid else "view-grid-symbolic",
            t(self.preferences.language, "view_list" if is_grid else "view_grid"),
        )
        button.set_tooltip_text(t(self.preferences.language, "tooltip_installed_layout"))
        button.get_accessible().set_name(t(self.preferences.language, "tooltip_installed_layout"))
        if getattr(self, "applications", None):
            self._render_applications_list()

    def on_applications_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.application_search_text = entry.get_text().strip()
        self._render_applications_list()

    def on_application_filter_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if not button.get_active():
            if not any(btn.get_active() for btn in self.application_filter_buttons.values()):
                button.set_active(True)
            return
        for item_source, item_button in self.application_filter_buttons.items():
            if item_source != source:
                item_button.set_active(False)
        self.application_filter_source = source
        if (
            source == "updates"
            and not self.applications_loading
            and not self.application_updates_scanned
        ):
            self._load_update_status_for_installed()
            self._render_applications_list()
            return
        self._render_applications_list()

    def on_reload_applications(self, *_args) -> None:
        self.reload_applications_async()

    def on_flatpak_cleanup(self, *_args) -> None:
        if self.applications_busy or self.store_busy or getattr(self, "_cleanup_plan_loading", False):
            return
        self._cleanup_plan_loading = True
        self.applications_flatpak_cleanup_btn.set_sensitive(False)

        def worker():
            try:
                plan = plan_cleanup(self.application_registry.runner)
                GLib.idle_add(self._show_flatpak_cleanup_plan, plan, None)
            except BackendError as exc:
                GLib.idle_add(self._show_flatpak_cleanup_plan, (), str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_flatpak_cleanup_plan(self, plan, error):
        self._cleanup_plan_loading = False
        self.applications_flatpak_cleanup_btn.set_sensitive(True)
        if error:
            self._show_error_dialog(error)
            return False
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "applications_flatpak_cleanup"), transient_for=self,
            modal=True, destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=600, height=340)
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        apply = dialog.add_button(t(lang, "cleanup_apply"), Gtk.ResponseType.OK)
        apply.get_style_context().add_class("destructive-action")
        apply.set_sensitive(bool(plan))
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        label = Gtk.Label(label=t(lang, "cleanup_preview" if plan else "cleanup_empty"), xalign=0)
        label.set_line_wrap(True)
        box = dialog.get_content_area()
        box.set_border_width(16)
        box.set_spacing(12)
        box.pack_start(label, False, False, 0)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text("\n".join(
            f"{t(lang, 'cleanup_scope_' + item.scope)}: {item.ref}" for item in plan
        ))
        scroller = Gtk.ScrolledWindow()
        scroller.add(view)
        box.pack_start(scroller, True, True, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not plan:
            return False
        self._run_application_task(
            action_name="flatpak_cleanup",
            worker_callable=lambda: apply_cleanup(self.application_registry.runner, plan),
            success_message_key="applications_flatpak_cleanup_done",
            progress_title_key="applications_flatpak_cleanup",
            refresh_after=False,
        )
        return False

    def on_check_for_updates(self, *_args) -> None:
        self._run_application_task(
            action_name="check_updates",
            worker_callable=self.application_registry.refresh_update_cache,
            success_message_key="applications_updates_checked",
            progress_title_key="applications_progress_check",
            refresh_after=True,
        )

    def on_update_all_applications(self, _button: Gtk.Button) -> None:
        updateable = [
            item for item in self._application_items_with_update_status() if item.update_available
        ]
        if not updateable:
            return
        if any(app.source == SOURCE_FIRMWARE for app in updateable) and not self._confirm_firmware_update():
            return
        self._run_application_task(
            action_name="update_all",
            worker_callable=lambda: self.application_registry.update_all(updateable),
            success_message_key="applications_update_done",
            progress_title_key="applications_progress_update_all",
            refresh_after=True,
        )

    def on_application_tree_activated(self, _tree: Gtk.TreeView, path, _col) -> None:
        model = self.applications_store
        it = model.get_iter(path)
        if it is None:
            return
        application: UnifiedApplication = model.get_value(it, _AC_APP)
        self.on_show_application_details(None, application)

    def on_application_tree_button_press(self, _tree: Gtk.TreeView, event) -> bool:
        if event.button == 3:
            path_info = self.applications_tree.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                path = path_info[0]
                model = self.applications_store
                it = model.get_iter(path)
                application: UnifiedApplication = model.get_value(it, _AC_APP)
                selection = self.applications_tree.get_selection()
                if not selection.path_is_selected(path):
                    selection.unselect_all()
                    selection.select_path(path)
                self._show_application_context_menu(application, event)
                return True
        return False

    def on_applications_tree_key_press(self, tree: Gtk.TreeView, event) -> bool:
        if Gdk.keyval_name(event.keyval) not in ("space", "KP_Space"):
            return False
        selection = tree.get_selection()
        model, paths = selection.get_selected_rows()
        path = paths[-1] if paths else tree.get_cursor()[0]
        if path is None:
            return False
        if selection.path_is_selected(path):
            selection.unselect_path(path)
        else:
            selection.select_path(path)
        return True

    def on_applications_tree_query_tooltip(
        self,
        treeview: Gtk.TreeView,
        x: int,
        y: int,
        _keyboard_mode: bool,
        tooltip: Gtk.Tooltip,
    ) -> bool:
        res = treeview.get_path_at_pos(x, y)
        if not res:
            return False
        path, column, _cell_x, _cell_y = res
        model = self.applications_store
        if model is None:
            return False
        try:
            it = model.get_iter(path)
        except Exception:
            return False
        if it is None:
            return False

        app: UnifiedApplication | None = model.get_value(it, _AC_APP)

        # Fare imlecinin üzerinde olduğu sütuna göre baloncuk (tooltip) göster
        if column == getattr(self, "applications_tree_col_location", None):
            loc = model.get_value(it, _AC_LOCATION)
            if loc and loc != "-":
                tooltip.set_text(loc)
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
        elif column == getattr(self, "applications_tree_col_version", None):
            ver = model.get_value(it, _AC_VERSION)
            if ver and ver != "-":
                tooltip.set_text(ver)
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
        elif column == getattr(self, "applications_tree_col_installed_date", None):
            dt = model.get_value(it, _AC_INSTALLED_DATE)
            if dt and dt != "-":
                tooltip.set_text(f"{t(self.preferences.language, 'applications_col_installed_date')}: {dt}")
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
        elif column == getattr(self, "applications_tree_col_last_updated", None):
            dt = model.get_value(it, _AC_LAST_UPDATED)
            if dt and dt != "-":
                tooltip.set_text(f"{t(self.preferences.language, 'applications_col_last_updated')}: {dt}")
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
        elif column == getattr(self, "applications_tree_col_app", None):
            name = model.get_value(it, _AC_NAME)
            pkg = (app.package_name or app.id) if app else ""
            summary = app.category if app and app.category else ""
            lines = [name]
            if pkg and pkg != name:
                lines.append(f"({pkg})")
            if summary:
                lines.append(summary)
            tooltip.set_text("\n".join(lines))
            treeview.set_tooltip_cell(tooltip, path, column, None)
            return True
        elif column == getattr(self, "applications_tree_col_size", None):
            sz = model.get_value(it, _AC_SIZE_STR)
            if sz and sz != "-":
                tooltip.set_text(f"{t(self.preferences.language, 'applications_col_size')}: {sz}")
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
        elif column == getattr(self, "applications_tree_col_source", None):
            src = model.get_value(it, _AC_SOURCE)
            if src:
                tooltip.set_text(f"{t(self.preferences.language, 'applications_col_source')}: {src}")
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True

        return False

    def on_application_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        count = len(paths)
        if count == 0:
            for btn in (
                self.applications_launch_btn,
                self.applications_details_btn,
                self.applications_action_update_btn,
                self.applications_action_location_btn,
                self.applications_action_remove_btn,
                self.applications_permissions_btn,
                self.applications_rollback_btn,
                self.applications_changelog_btn,
                self.applications_export_selected_btn,
            ):
                btn.set_sensitive(False)
            self.applications_bulk_remove_btn.set_sensitive(False)
            for item in self._advanced_action_menu_items.values():
                item.set_sensitive(False)
            if not self.applications_busy and not self.applications_loading:
                self._set_applications_status(t(self.preferences.language, "applications_select_hint"), "#666666")
            return

        self.applications_export_selected_btn.set_sensitive(True)
        if count == 1:
            it = model.get_iter(paths[0])
            application: UnifiedApplication = model.get_value(it, _AC_APP)
            self.applications_launch_btn.set_sensitive(bool(application.executable))
            self.applications_details_btn.set_sensitive(True)
            self.applications_action_update_btn.set_sensitive(application.update_available)
            self.applications_action_location_btn.set_sensitive(
                bool(application.install_path or application.desktop_file)
            )
            self.applications_action_remove_btn.set_sensitive(application.source != SOURCE_FIRMWARE)
            is_flatpak = application.source == SOURCE_FLATPAK
            self.applications_permissions_btn.set_sensitive(is_flatpak)
            self.applications_rollback_btn.set_sensitive(is_flatpak)
            self.applications_changelog_btn.set_sensitive(is_native_source(application.source))
        else:
            self.applications_launch_btn.set_sensitive(False)
            self.applications_details_btn.set_sensitive(False)
            self.applications_action_location_btn.set_sensitive(False)
            self.applications_permissions_btn.set_sensitive(False)
            self.applications_rollback_btn.set_sensitive(False)
            self.applications_changelog_btn.set_sensitive(False)
            selected_apps = [model.get_value(model.get_iter(p), _AC_APP) for p in paths]
            self.applications_action_update_btn.set_sensitive(any(a.update_available for a in selected_apps))
            self.applications_action_remove_btn.set_sensitive(
                any(a.source != SOURCE_FIRMWARE for a in selected_apps)
            )
        self.applications_bulk_remove_btn.set_sensitive(
            any(
                model.get_value(model.get_iter(path), _AC_APP).source != SOURCE_FIRMWARE
                for path in paths
            )
        )
        for attribute, item in self._advanced_action_menu_items.items():
            item.set_sensitive(getattr(self, attribute).get_sensitive())

    def _on_selected_app_action(self, callback: Callable) -> None:
        sel = self.applications_tree.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            return
        it = model.get_iter(paths[0])
        app: UnifiedApplication = model.get_value(it, _AC_APP)
        callback(None, app)

    def _show_application_context_menu(self, application: UnifiedApplication, event) -> None:
        menu = Gtk.Menu()
        menu.get_style_context().add_class("icon-settings-window")

        item_details = Gtk.MenuItem(label=t(self.preferences.language, "applications_details"))
        item_details.connect("activate", lambda _: self.on_show_application_details(None, application))
        menu.append(item_details)

        item_launch = Gtk.MenuItem(label=t(self.preferences.language, "applications_launch"))
        item_launch.set_sensitive(bool(application.executable))
        item_launch.connect("activate", lambda _: self.on_launch_application(None, application))
        menu.append(item_launch)

        if application.update_available:
            item_up = Gtk.MenuItem(label=t(self.preferences.language, "applications_update"))
            item_up.connect("activate", lambda _: self.on_update_application(None, application))
            menu.append(item_up)

        item_loc = Gtk.MenuItem(label=t(self.preferences.language, "applications_open_location"))
        item_loc.set_sensitive(bool(application.install_path or application.desktop_file))
        item_loc.connect("activate", lambda _: self.on_open_application_location(None, application))
        menu.append(item_loc)

        if application.source == SOURCE_FLATPAK:
            item_perm = Gtk.MenuItem(label=t(self.preferences.language, "flatpak_permissions_btn"))
            item_perm.connect("activate", lambda _: self.on_flatpak_permissions(None, application))
            menu.append(item_perm)

            item_rollback = Gtk.MenuItem(label=t(self.preferences.language, "flatpak_rollback_menu"))
            item_rollback.connect("activate", lambda _: self.on_flatpak_rollback(None, application))
            menu.append(item_rollback)

        if is_native_source(application.source):
            item_changelog = Gtk.MenuItem(label=t(self.preferences.language, "changelog_menu"))
            item_changelog.connect("activate", lambda _: self.on_show_changelog(None, application))
            menu.append(item_changelog)

        if application.source != SOURCE_FIRMWARE:
            menu.append(Gtk.SeparatorMenuItem())
            item_del = Gtk.MenuItem(label=t(self.preferences.language, "applications_remove"))
            item_del.get_style_context().add_class("destructive-action")
            item_del.connect("activate", lambda _: self.on_remove_application(None, application))
            menu.append(item_del)

        menu.show_all()
        menu.popup_at_pointer(event)

    def on_show_application_details(self, _button, application: UnifiedApplication) -> None:
        def _handle_detail_action(action: str, app: UnifiedApplication):
            if action == "launch":
                self.on_launch_application(None, app)
            elif action == "update":
                self.on_update_application(None, app)
            elif action == "remove":
                self.on_remove_application(None, app)
            elif action == "location":
                self.on_open_application_location(None, app)
            elif action == "permissions":
                self.on_flatpak_permissions(None, app)
            elif action == "rollback":
                self.on_flatpak_rollback(None, app)
            elif action == "changelog":
                self.on_show_changelog(None, app)

        toplevel = self.get_toplevel() if hasattr(self, "get_toplevel") else None
        parent_win = toplevel if isinstance(toplevel, Gtk.Window) else None
        dialog = InstalledAppDetailsDialog(
            application=application,
            registry=self.application_registry,
            language=self.preferences.language,
            parent=parent_win,
            on_action_callback=_handle_detail_action,
        )
        dialog.connect("response", lambda widget, _response: widget.destroy())
        dialog.show_all()
        dialog.present()

    def on_launch_application(self, _button, application: UnifiedApplication) -> None:
        try:
            self.application_registry.launch(application)
        except BackendError as exc:
            self._set_applications_status(self._application_error_message(str(exc)), "red")

    def on_update_application(self, _button, application: UnifiedApplication) -> None:
        if application.source == SOURCE_FIRMWARE and not self._confirm_firmware_update():
            return
        self._run_application_task(
            action_name="update",
            worker_callable=lambda: self.application_registry.update(application),
            success_message_key="applications_update_done",
            progress_title_key="applications_progress_update",
            refresh_after=True,
            progress_message=application.name,
        )

    def on_open_application_location(self, _button, application: UnifiedApplication) -> None:
        try:
            self.application_registry.open_location(application)
        except BackendError as exc:
            self._set_applications_status(self._application_error_message(str(exc)), "red")

    def on_remove_application(self, _button, application: UnifiedApplication) -> None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "applications_remove_confirm_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=520, height=320)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(16)
        content.set_margin_bottom(8)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.pack_start(
            Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.DIALOG), False, False, 0
        )
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{t(self.preferences.language, 'applications_remove_confirm_title')}</b>")
        title_label.set_xalign(0)
        header.pack_start(title_label, True, True, 0)
        content.pack_start(header, False, False, 0)
        body = Gtk.Label(
            label=t(self.preferences.language, "applications_remove_confirm_body", name=application.name)
        )
        body.set_xalign(0)
        body.set_line_wrap(True)
        content.pack_start(body, False, False, 0)
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = dialog.add_button(t(self.preferences.language, "applications_remove"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")

        add_sensitive_removal_confirmation(content, del_btn, [application], self.preferences.language)
        purge_check = Gtk.CheckButton(label=t(self.preferences.language, "applications_purge_confirm"))
        purge_check.set_margin_start(16)
        purge_check.set_margin_bottom(8)
        content.pack_start(purge_check, False, False, 0)
        content.show_all()

        resp = dialog.run()
        purge = purge_check.get_active()
        dialog.destroy()
        if resp != Gtk.ResponseType.OK:
            return

        self._run_application_task(
            action_name="remove",
            worker_callable=lambda: self.application_registry.remove(application, purge=purge),
            success_message_key="applications_remove_done",
            progress_title_key="applications_progress_remove",
            refresh_after=True,
            progress_message=application.name,
        )

    def reload_applications_async(self) -> None:
        if self.applications_loading:
            return
        invalidate = getattr(self.application_registry, "invalidate_application_cache", None)
        if callable(invalidate):
            invalidate()
        self.applications_loading = True
        self._application_update_scan_token += 1
        self.application_updates_loading = False
        self.application_updates_scanned = False
        self._application_initial_load_needs_updates = True
        self.application_update_only_items = []
        self._application_load_started_at = time.perf_counter()
        self.application_load_metrics = {
            "first_snapshot_ms": None,
            "first_meaningful_ms": None,
            "complete_ms": None,
        }
        self.installed_state.show_state(t(self.preferences.language, "applications_loading"), loading=True)
        self._set_application_controls_sensitive(False)
        self._set_applications_status(t(self.preferences.language, "applications_loading"), "#666666")
        threading.Thread(target=self._load_applications_worker, daemon=True).start()

    def _load_applications_worker(self) -> None:
        def publish(snapshot, complete):
            GLib.idle_add(self._finish_applications_load, snapshot, complete)

        progressive_loader = getattr(self.application_registry, "load_progressive", None)
        try:
            if callable(progressive_loader):
                progressive_loader(publish, include_updates=False)
            else:
                GLib.idle_add(self._finish_applications_load, self.application_registry.load(), True)
        except Exception as exc:
            failed = ApplicationSnapshot([], provider_errors=[str(exc)])
            GLib.idle_add(self._finish_applications_load, failed, True)

    def _load_update_status_for_installed(self) -> None:
        """Load update metadata only when the user asks for that filter."""
        if self.application_updates_loading or self.application_updates_scanned:
            return

        self._application_update_scan_token += 1
        scan_token = self._application_update_scan_token
        self.application_updates_loading = True
        self._render_applications_list()
        self.installed_state.show_state(
            t(self.preferences.language, "updates_loading"), loading=True
        )
        self._set_applications_status(t(self.preferences.language, "updates_loading"), "#666666")
        current_applications = list(self.applications)

        def worker() -> None:
            try:
                snapshot = self.application_registry.load(include_updates=True)
            except Exception as exc:
                snapshot = ApplicationSnapshot(current_applications, provider_errors=[str(exc)])
            GLib.idle_add(self._finish_update_status_for_installed, snapshot, scan_token)

        threading.Thread(target=worker, daemon=True, name="installed-update-status").start()

    def _finish_update_status_for_installed(
        self, snapshot: ApplicationSnapshot, scan_token: int | None = None
    ) -> bool:
        if scan_token is not None and scan_token != self._application_update_scan_token:
            return False
        self.application_updates_loading = False
        self.application_updates_scanned = True
        current_by_package = {
            (app.source, app.package_name)
            for app in self.applications
            if app.package_name
        }
        current_by_fallback = {
            (app.source, app.install_path or app.id)
            for app in self.applications
            if not app.package_name
        }
        update_status = {
            (app.source, app.package_name): app
            for app in snapshot.applications
            if app.package_name
        }
        fallback_status = {
            (app.source, app.install_path or app.id): app
            for app in snapshot.applications
            if not app.package_name
        }
        matched_update_ids: set[str] = set()
        merged_applications: list[UnifiedApplication] = []
        for application in self.applications:
            status = (
                update_status.get((application.source, application.package_name))
                if application.package_name
                else fallback_status.get((application.source, application.install_path or application.id))
            )
            if status is None:
                merged_applications.append(application)
                continue
            merged_applications.append(
                replace(
                    application,
                    update_available=status.update_available,
                    update_note=status.update_note,
                )
            )
            matched_update_ids.add(status.id)

        self.application_update_only_items = []
        for candidate in snapshot.applications:
            if not candidate.update_available or candidate.id in matched_update_ids:
                continue
            if candidate.package_name and (candidate.source, candidate.package_name) in current_by_package:
                continue
            if not candidate.package_name and (candidate.source, candidate.install_path or candidate.id) in current_by_fallback:
                continue
            self.application_update_only_items.append(candidate)
        self.applications = merged_applications
        self.application_issues = snapshot.issues
        self.application_provider_errors = snapshot.provider_errors
        self.application_provider_notices = snapshot.provider_notices
        self.installed_package_ids = {
            f"{app.source}:{app.package_name}" for app in self.applications if app.package_name
        }
        self.installed_package_ids.update(
            f"{app.source}:{app.package_name}"
            for app in self.application_update_only_items
            if app.package_name
        )
        self._update_category_combo()
        self._render_applications_list()
        self._render_application_diagnostics()

        if hasattr(self, "updates_model"):
            from sourcedock.backend.updates import build_update_catalog

            self.update_items = build_update_catalog(
                self._application_items_with_update_status(),
                self.packages,
                self.application_registry.native_provider.source,
            )
            self._refresh_update_count()

        update_count = sum(
            1 for item in self._application_items_with_update_status() if item.update_available
        )
        self.applications_update_all_btn.set_sensitive(update_count > 0)
        status_key = "applications_load_partial" if self.application_provider_errors else "applications_loaded"
        self._set_applications_status(t(self.preferences.language, status_key), "#666666")
        return False

    def _finish_applications_load(self, snapshot: ApplicationSnapshot, complete: bool = True) -> bool:
        if not hasattr(self, "_application_load_started_at"):
            self._application_load_started_at = time.perf_counter()
        if self.application_load_metrics.get("first_snapshot_ms") is None:
            self.application_load_metrics["first_snapshot_ms"] = round(
                (time.perf_counter() - self._application_load_started_at) * 1000, 1
            )
        if snapshot.applications and self.application_load_metrics.get("first_meaningful_ms") is None:
            self.application_load_metrics["first_meaningful_ms"] = round(
                (time.perf_counter() - self._application_load_started_at) * 1000, 1
            )
        if complete:
            self.application_load_metrics["complete_ms"] = round(
                (time.perf_counter() - self._application_load_started_at) * 1000, 1
            )
        self.applications = snapshot.applications
        self.application_update_only_items = []
        self.application_issues = snapshot.issues
        self.application_provider_errors = snapshot.provider_errors
        self.application_provider_notices = snapshot.provider_notices
        self.installed_package_ids = {
            f"{app.source}:{app.package_name}" for app in self.applications if app.package_name
        }

        self.applications_loading = not complete
        self._set_application_controls_sensitive(True)
        self._update_category_combo()
        self._render_applications_list()
        self._render_application_diagnostics()
        if self.application_filter_source == "updates" and self.applications_loading:
            self.installed_state.show_state(
                t(self.preferences.language, "updates_loading"), loading=True
            )
        elif self.applications:
            self.installed_state.show_content()
        elif complete:
            self.installed_state.show_state(
                t(self.preferences.language, "installed_empty"),
                t(self.preferences.language, "installed_empty_body"),
                error=bool(self.application_provider_errors),
                retry_callback=self.reload_applications_async if self.application_provider_errors else None,
                retry_label=t(self.preferences.language, "retry_action"),
            )
        if hasattr(self, "updates_model"):
            from sourcedock.backend.updates import build_update_catalog

            self.update_items = build_update_catalog(
                self.applications, self.packages, self.application_registry.native_provider.source
            )
            self._refresh_update_count()

        update_count = sum(1 for item in self.applications if item.update_available)
        self.applications_update_all_btn.set_sensitive(update_count > 0)
        status_msg = t(self.preferences.language, "applications_loaded")
        if not complete:
            status_msg = t(self.preferences.language, "applications_load_partial")
        if self.application_provider_errors:
            status_msg = t(self.preferences.language, "applications_load_partial")
        elif complete:
            _model, selected_paths = self.applications_tree.get_selection().get_selected_rows()
            if not selected_paths:
                status_msg = t(self.preferences.language, "applications_select_hint")
        self._set_applications_status(status_msg, "#666666")
        if (
            complete
            and self._application_initial_load_needs_updates
            and not self.application_updates_scanned
        ):
            self._application_initial_load_needs_updates = False
            self._load_update_status_for_installed()
        return False

    def _run_application_task(
        self,
        action_name: str,
        worker_callable: Callable[[], None],
        success_message_key: str,
        progress_title_key: str,
        refresh_after: bool = False,
        progress_message: str = "",
        retry: bool = False,
    ) -> None:
        if self.applications_busy or self.store_busy:
            return
        self.applications_busy = True
        self._set_application_controls_sensitive(False)
        self._set_applications_status(t(self.preferences.language, "store_action_running"), "#666666")

        cached_pwd = self.get_cached_sudo_password() if hasattr(self, "get_cached_sudo_password") else None
        if not retry and cached_pwd:
            self.application_registry.set_sudo_password(cached_pwd)

        lang = self.preferences.language
        self._active_op_seq += 1
        op_key = f"app_{self._active_op_seq}"
        op_id = f"op_installed_{self._active_op_seq}_{int(time.monotonic() * 1000)}"
        runner = self.application_registry.runner
        cancel_action = lambda: runner.cancel_current(target=op_id)

        self._register_active_op(
            op_key,
            f"app {action_name}",
            progress_message or action_name,
            None,
            cancel_fn=cancel_action,
        )

        progress_dialog = OperationProgressWindow(
            title=t(lang, progress_title_key),
            message=progress_message,
            parent=self,
            on_progress=lambda f, lbl: self._update_op_row(op_key, f, lbl),
            language=lang,
            cancel_fn=cancel_action,
        )
        runner.set_output_callback(
            lambda line: GLib.idle_add(progress_dialog.append_log, line),
            op_id=op_id,
        )

        def worker():
            runner.bind_thread_op(op_id)
            try:
                worker_callable()
            except AuthRequiredError as exc:
                runner.set_output_callback(None, op_id=op_id)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(
                    self._handle_application_auth_required,
                    exc,
                    action_name,
                    worker_callable,
                    success_message_key,
                    progress_title_key,
                    refresh_after,
                    progress_message,
                    retry,
                )
            except BackendError as exc:
                err_text = str(exc)
                ctx = runner.get_operation_context(op_id) if hasattr(runner, "get_operation_context") else None
                if ctx and getattr(ctx, "lingering", False) is True:
                    notice = "İşlem arka planda güvenle tamamlanması bekleniyor..."
                    def _log_inst_lingering():
                        progress_dialog.append_log(notice)
                        return False
                    GLib.idle_add(_log_inst_lingering)

                    def _finalize_inst(retcode: int | None):
                        runner.set_output_callback(None, op_id=op_id)
                        if retcode == 0:
                            GLib.idle_add(self._unregister_active_op, op_key, True, t(lang, success_message_key))
                            msg = t(self.preferences.language, success_message_key)
                            GLib.idle_add(progress_dialog.finish, True, msg)
                            GLib.idle_add(self._finish_application_task, True, msg, refresh_after)
                        else:
                            fail_msg = f"{err_text} (Kod {retcode})"
                            GLib.idle_add(self._unregister_active_op, op_key, False, fail_msg)
                            msg = self._application_error_message(fail_msg)
                            GLib.idle_add(progress_dialog.finish, False, msg)
                            GLib.idle_add(self._finish_application_task, False, msg, refresh_after)

                    wait_timeout = getattr(runner, "_lingering_wait_timeout", 1800)
                    completed = ctx.completed_event.wait(timeout=wait_timeout)
                    if completed:
                        _finalize_inst(ctx.returncode)
                        return
                    else:
                        def _log_inst_running():
                            progress_dialog.append_log("İşlem arka planda güvenle devam ediyor...")
                            return False
                        GLib.idle_add(_log_inst_running)

                        def _watch_inst():
                            ctx.completed_event.wait()
                            _finalize_inst(ctx.returncode)
                        threading.Thread(target=_watch_inst, daemon=True, name=f"watch-inst-{op_id}").start()
                        return
                runner.set_output_callback(None, op_id=op_id)
                GLib.idle_add(self._unregister_active_op, op_key, False, str(exc))
                msg = self._application_error_message(str(exc))
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, refresh_after)
            except Exception as exc:
                runner.set_output_callback(None, op_id=op_id)
                GLib.idle_add(self._unregister_active_op, op_key, False, str(exc))
                msg = str(exc)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, refresh_after)
            else:
                runner.set_output_callback(None, op_id=op_id)
                GLib.idle_add(self._unregister_active_op, op_key, True, t(lang, success_message_key))
                msg = t(self.preferences.language, success_message_key)
                GLib.idle_add(progress_dialog.finish, True, msg)
                GLib.idle_add(self._finish_application_task, True, msg, refresh_after)
            finally:
                runner.unbind_thread_op(op_id)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_application_auth_required(
        self,
        exc: AuthRequiredError,
        action_name: str,
        worker_callable: Callable[[], None],
        success_message_key: str,
        progress_title_key: str,
        refresh_after: bool,
        progress_message: str,
        retry: bool,
    ) -> bool:
        if retry or exc.password_failed:
            if hasattr(self, "clear_cached_sudo_password"):
                self.clear_cached_sudo_password()
            self._cached_sudo_password = None
        password = self._ask_sudo_password(retry=retry or exc.password_failed)
        if password is None:
            if hasattr(self, "clear_cached_sudo_password"):
                self.clear_cached_sudo_password()
            self._cached_sudo_password = None
            self._finish_application_task(False, t(self.preferences.language, "status_cancelled"), False)
            return False
        if hasattr(self, "set_cached_sudo_password"):
            self.set_cached_sudo_password(password)
        else:
            self._cached_sudo_password = password
        self.application_registry.set_sudo_password(password)
        self.applications_busy = False
        self._run_application_task(
            action_name=action_name,
            worker_callable=worker_callable,
            success_message_key=success_message_key,
            progress_title_key=progress_title_key,
            refresh_after=refresh_after,
            progress_message=progress_message,
            retry=True,
        )
        return False

    def _finish_application_task(self, success: bool, message: str, refresh_after: bool) -> bool:
        self.applications_busy = False
        self._set_application_controls_sensitive(True)
        self._set_applications_status(message, "#1f7a1f" if success else "red")
        if refresh_after:
            invalidate = getattr(self.application_registry, "invalidate_application_cache", None)
            if callable(invalidate):
                try:
                    invalidate(clear_persisted=True)
                except TypeError:
                    invalidate()
            store_invalidate = getattr(getattr(self, "store_registry", None), "invalidate_search_cache", None)
            if callable(store_invalidate):
                store_invalidate()
            self.reload_applications_async()
            if self.pages.get_current_page() == 2:
                self.reload_packages_async()
            if self.pages.get_current_page() == 4:
                self._reload_updates_async()
        return False

    def _get_app_size_fallback(self, app: UnifiedApplication) -> int | None:
        if app.installed_size_kib:
            return app.installed_size_kib
        if app.executable:
            cmd = app.executable.split()[0].strip("\"'") if app.executable else ""
            if cmd and os.path.isfile(cmd):
                try:
                    return os.path.getsize(cmd) // 1024
                except OSError:
                    pass
        if app.install_path and os.path.exists(app.install_path):
            try:
                if os.path.isfile(app.install_path):
                    return os.path.getsize(app.install_path) // 1024
            except OSError:
                pass
        return None

    def _get_app_date_fallback(self, app: UnifiedApplication) -> tuple[str, str]:
        inst_date = app.installed_date
        last_upd = app.last_updated
        if not inst_date and not last_upd and app.desktop_file and os.path.isfile(app.desktop_file):
            try:
                mtime = os.path.getmtime(app.desktop_file)
                from datetime import datetime

                d = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                inst_date = d
                last_upd = d
            except OSError:
                pass
        return inst_date or "-", last_upd or inst_date or "-"

    def _render_applications_list(self) -> None:
        if not hasattr(self, "applications_store") or self.applications_store is None:
            return

        # Capture current scroll positions and selected item before clearing
        saved_table_scroll = 0.0
        if hasattr(self, "apps_scroller") and self.apps_scroller is not None:
            vadj = self.apps_scroller.get_vadjustment()
            if vadj:
                saved_table_scroll = vadj.get_value()
        saved_cards_scroll = 0.0
        if hasattr(self, "cards_scroll") and self.cards_scroll is not None:
            vadj = self.cards_scroll.get_vadjustment()
            if vadj:
                saved_cards_scroll = vadj.get_value()

        selected_app_id = None
        if hasattr(self, "applications_tree") and self.applications_tree is not None:
            selection = self.applications_tree.get_selection()
            if selection:
                model, paths = selection.get_selected_rows()
                if paths:
                    try:
                        it = model.get_iter(paths[0])
                        app = model.get_value(it, 9)
                        if app:
                            selected_app_id = getattr(app, "id", None)
                    except Exception:
                        pass

        self.applications_store.clear()
        filtered = self._filtered_application_items()
        self.filtered_applications = filtered

        for app in filtered:
            size_kib = self._get_app_size_fallback(app)
            inst_date_str, last_upd_str = self._get_app_date_fallback(app)
            self.applications_store.append(
                [
                    self._get_app_pixbuf(app),
                    app.name,
                    self._application_source_label(app.source),
                    app.version or "-",
                    size_kib or 0,
                    self._format_application_size(size_kib),
                    inst_date_str,
                    last_upd_str,
                    app.install_path or app.desktop_file or "-",
                    app,
                ]
            )
        # Only build widgets for the active representation. The other view is
        # populated lazily when the user switches to it.
        is_grid = (
            hasattr(self, "applications_view_stack")
            and self.applications_view_stack.get_visible_child_name() == "cards"
        )
        if is_grid and hasattr(self, "applications_cards") and self.applications_cards is not None:
            for child in self.applications_cards.get_children():
                self.applications_cards.remove(child)
            for app in filtered:
                pixbuf = self._get_app_pixbuf(app, 48)
                card = InstalledAppCard(
                    app,
                    pixbuf,
                    on_details=lambda a: self.on_show_application_details(None, a),
                    language=self.preferences.language,
                )
                self.applications_cards.add(card)
            self.applications_cards.show_all()

        def _restore_scroll_and_selection():
            if hasattr(self, "apps_scroller") and self.apps_scroller is not None:
                vadj = self.apps_scroller.get_vadjustment()
                if vadj:
                    max_scroll = max(0.0, vadj.get_upper() - vadj.get_page_size())
                    vadj.set_value(min(saved_table_scroll, max_scroll))
            if hasattr(self, "cards_scroll") and self.cards_scroll is not None:
                vadj = self.cards_scroll.get_vadjustment()
                if vadj:
                    max_scroll = max(0.0, vadj.get_upper() - vadj.get_page_size())
                    vadj.set_value(min(saved_cards_scroll, max_scroll))
            if selected_app_id and hasattr(self, "applications_tree") and self.applications_store:
                for row in self.applications_store:
                    app = row[9]
                    if app and getattr(app, "id", None) == selected_app_id:
                        self.applications_tree.get_selection().select_iter(row.iter)
                        break
            return False

        GLib.idle_add(_restore_scroll_and_selection)

        total = len(self._application_items_with_update_status())

        shown = len(filtered)
        show_technical = getattr(self.preferences, "show_technical_packages", False)
        hidden = (
            max(total - shown, 0)
            if self.application_filter_source == "all"
            and self.application_filter_category == "__all__"
            and not self.application_search_text
            and not show_technical
            else 0
        )
        summary_key = "applications_count_summary_hidden" if hidden else "applications_count_summary"
        scanning_applications = self.applications_loading
        scanning_updates = (
            self.application_filter_source == "updates" and self.application_updates_loading
        )
        if scanning_applications:
            self.applications_summary_label.set_text(
                t(self.preferences.language, "applications_loading")
            )
        elif scanning_updates:
            self.applications_summary_label.set_text(
                t(self.preferences.language, "updates_loading")
            )
        else:
            self.applications_summary_label.set_text(
                t(self.preferences.language, summary_key, count=shown, total=total, hidden=hidden)
            )
        if hidden and not scanning_updates:
            self.applications_summary_label.set_tooltip_text(
                t(self.preferences.language, "tooltip_installed_summary_hidden")
            )
        else:
            self.applications_summary_label.set_tooltip_text(None)
        if self.application_updates_loading and self.application_filter_source == "updates":
            self.installed_state.show_state(
                t(self.preferences.language, "updates_loading"), loading=True
            )
        elif not self.applications_loading:
            if filtered:
                self.installed_state.show_content()
            else:
                if self.application_search_text:
                    self.installed_state.show_state(
                        t(
                            self.preferences.language,
                            "installed_search_empty",
                            query=self.application_search_text,
                        ),
                        t(self.preferences.language, "installed_search_empty_body"),
                        retry_callback=self._clear_application_search,
                        retry_label=t(self.preferences.language, "clear_search"),
                    )
                elif self.application_filter_source == "updates":
                    self.installed_state.show_state(
                        t(self.preferences.language, "updates_empty"),
                        t(self.preferences.language, "updates_empty_body"),
                    )
                else:
                    self.installed_state.show_state(t(self.preferences.language, "installed_empty"))

    def _clear_application_search(self) -> None:
        self._suppress_global_search_changed = True
        try:
            self.applications_search_entry.set_text("")
            self.header_search.set_text("")
        finally:
            self._suppress_global_search_changed = False
        self.application_search_text = ""
        self._render_applications_list()

    def _scale_pixbuf_safe(self, pb: GdkPixbuf.Pixbuf | None, size: int = 24) -> GdkPixbuf.Pixbuf | None:
        if pb is None:
            return None
        try:
            w = pb.get_width()
            h = pb.get_height()
            if w != size or h != size:
                return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            pass
        return pb

    def _get_app_pixbuf(self, application: UnifiedApplication, size: int = 32) -> GdkPixbuf.Pixbuf | None:
        cache_key = f"app:{application.id}:{size}"
        if cache_key in self._icon_pixbuf_cache:
            return self._icon_pixbuf_cache[cache_key]

        icon_name = application.icon
        if icon_name and os.path.exists(icon_name):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, size, size, True)
                if pb:
                    pb = self._scale_pixbuf_safe(pb, size)
                self._icon_pixbuf_cache[cache_key] = pb
                return pb
            except Exception:
                pass

        if application.source == SOURCE_FLATPAK:
            flatpak_path = find_flatpak_icon_path(application.package_name or application.id)
            if flatpak_path:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(flatpak_path, size, size, True)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass

        theme = Gtk.IconTheme.get_default()
        fallback_by_source = {
            SOURCE_FIRMWARE: "computer-symbolic",
            SOURCE_FLATPAK: "package-x-generic",
            SOURCE_SNAP: "application-x-executable",
        }
        generic_names = {"application-x-executable", "application-x-executable-symbolic"}
        fallback_name = fallback_by_source.get(application.source, "package-x-generic")
        candidates = [name for name in (icon_name, application.package_name) if name and name not in generic_names]
        candidates.append(fallback_name)
        for name in candidates:
            if name and theme.has_icon(name):
                try:
                    pb = theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    if pb:
                        pb = self._scale_pixbuf_safe(pb, size)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        self._icon_pixbuf_cache[cache_key] = None
        return None

    def _render_application_diagnostics(self) -> None:
        for child in self.applications_diagnostics_list.get_children():
            self.applications_diagnostics_list.remove(child)

        lang = self.preferences.language
        all_notes = []
        timeout_sources = []
        for error in self.application_provider_errors:
            source, _, detail = error.partition(":")
            if "timeout" in detail.casefold():
                timeout_sources.append(source_name(lang, source.strip().lower()))
            else:
                all_notes.append(("dialog-warning-symbolic", translate_provider_error(lang, error)))
        if timeout_sources:
            unique_sources = list(dict.fromkeys(timeout_sources))
            all_notes.append(
                (
                    "dialog-warning-symbolic",
                    f"{', '.join(unique_sources)}: {t(lang, 'provider_timeout', source='').lstrip()}",
                )
            )
        all_notes.extend(
            ("dialog-information-symbolic", translate_provider_notice(lang, notice))
            for notice in dict.fromkeys(self.application_provider_notices)
        )
        detail_keys = {
            "No icon is set.": "diagnostics_missing_icon",
            "Desktop launcher has no command.": "diagnostics_missing_command",
            "Linked AppImage file is missing.": "diagnostics_missing_appimage",
        }
        missing_appimages = []
        for issue in self.application_issues:
            if issue.detail == "Linked AppImage file is missing.":
                missing_appimages.append(issue.title)
                continue
            detail = t(lang, detail_keys[issue.detail]) if issue.detail in detail_keys else issue.detail
            all_notes.append(("dialog-information-symbolic", f"{issue.title}: {detail}"))
        if missing_appimages:
            names = ", ".join(missing_appimages[:3])
            if len(missing_appimages) > 3:
                names += f" (+{len(missing_appimages) - 3})"
            all_notes.append(
                (
                    "dialog-information-symbolic",
                    f"{names}: {t(lang, 'diagnostics_missing_appimage')}",
                )
            )

        if not all_notes:
            self.applications_diagnostics_label.set_text(t(lang, "diagnostics_empty"))
            return

        self.applications_diagnostics_label.set_text(t(
            lang, "diagnostics_record" if len(all_notes) == 1 else "diagnostics_records", count=len(all_notes),
        ))
        for icon, note in all_notes[:10]:
            row = Gtk.Box(spacing=8)
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            image.set_valign(Gtk.Align.START)
            row.pack_start(image, False, False, 0)
            lbl = Gtk.Label(label=note)
            lbl.set_xalign(0)
            lbl.set_line_wrap(True)
            lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_selectable(True)
            row.pack_start(lbl, True, True, 0)
            self.applications_diagnostics_list.add(row)
        self.applications_diagnostics_list.show_all()

    def _application_items_with_update_status(self) -> list[UnifiedApplication]:
        """Return the base inventory plus update-only technical entries."""
        return [*self.applications, *self.application_update_only_items]

    def _filtered_application_items(self) -> list[UnifiedApplication]:
        source = self.application_filter_source
        cat = self.application_filter_category
        query = self.application_search_text.lower()

        results = []
        show_technical = getattr(self.preferences, "show_technical_packages", False)
        if source == "updates" or (source == "all" and show_technical):
            applications = self._application_items_with_update_status()
        else:
            applications = self.applications
        for app in applications:
            if (
                source == "all"
                and not show_technical
                and not app.desktop_file
                and app.source in (SOURCE_FLATPAK, SOURCE_SNAP, SOURCE_FIRMWARE)
            ):
                continue
            if source == "updates" and not app.update_available:
                continue
            if source not in ("all", "updates"):
                if source in NATIVE_SOURCES:
                    if app.source not in NATIVE_SOURCES:
                        continue
                elif source == "other":
                    if app.source in NATIVE_SOURCES or app.source in (SOURCE_FLATPAK, SOURCE_SNAP):
                        continue
                elif app.source != source:
                    continue
            if cat != "__all__" and cat.lower() not in app.category.lower():
                continue
            if query and query not in app.name.lower() and query not in app.package_name.lower():
                continue
            results.append(app)
        return results

    def _set_application_controls_sensitive(self, enabled: bool) -> None:
        self.applications_search_entry.set_sensitive(enabled)
        self.applications_refresh_btn.set_sensitive(enabled)
        self.applications_check_updates_btn.set_sensitive(enabled)
        for btn in self.application_filter_buttons.values():
            btn.set_sensitive(enabled)

    def _set_applications_status(self, message: str, color: str) -> None:
        set_status(self.applications_status, message, color == "red")

    def _application_source_label(self, source: str) -> str:
        lang = self.preferences.language
        if source == "all":
            return t(lang, "applications_source_all")
        if source == "updates":
            return t(lang, "applications_source_updates")
        if source == "other":
            return t(lang, "applications_source_other")
        labels = {
            SOURCE_APPIMAGE: "AppImage",
            SOURCE_PORTABLE: t(lang, "source_portable"),
            SOURCE_FIRMWARE: t(lang, "source_firmware"),
        }
        return labels.get(source, source_name(lang, source))

    def _category_display_name(self, category: str, lang: str) -> str:
        cat_lower = category.lower().strip()
        mapping = {
            "audiovideo": "category_audiovideo",
            "audio": "category_audio",
            "video": "category_video",
            "development": "category_development",
            "education": "category_education",
            "game": "category_game",
            "games": "category_game",
            "graphics": "category_graphics",
            "network": "category_network",
            "office": "category_office",
            "science": "category_science",
            "settings": "category_settings",
            "system": "category_system",
            "utility": "category_utility",
            "utilities": "category_utility",
        }
        key = mapping.get(cat_lower)
        if key:
            return t(lang, key)
        return category

    def _application_error_message(self, message: str) -> str:
        return translate_backend_message(self.preferences.language, message)

    def _format_application_size(self, kib: int | None) -> str:
        if kib is None:
            return "-"
        if kib >= 1024 * 1024:
            return f"{kib / (1024 * 1024):.1f} GB"
        if kib >= 1024:
            return f"{kib / 1024:.1f} MB"
        return f"{kib} KB"

    def _update_category_combo(self) -> None:
        if not hasattr(self, "applications_category_combo"):
            return
        current = self.applications_category_combo.get_active_id() or "__all__"
        cats = sorted({app.category for app in self.applications if app.category})
        self.applications_category_combo.remove_all()
        lang = self.preferences.language
        self.applications_category_combo.append("__all__", t(lang, "applications_category_all"))
        for c in cats:
            label = self._category_display_name(c, lang)
            self.applications_category_combo.append(c, label)
        if current in {"__all__"} | set(cats):
            self.applications_category_combo.set_active_id(current)
        else:
            self.applications_category_combo.set_active(0)

    def _on_category_filter_changed(self, combo: Gtk.ComboBoxText) -> None:
        active_id = combo.get_active_id() or "__all__"
        self.application_filter_category = active_id
        self._render_applications_list()

    def on_export_application_list(self, _button) -> None:
        json_data = self.application_registry.export_app_list()
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
        dialog.set_current_name("installed_applications.json")
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            if filename:
                with open(filename, "w", encoding="utf-8") as fh:
                    fh.write(json_data)
                self._set_applications_status(
                    f"{t(self.preferences.language, 'status_exported')}: {filename}", "#1f7a1f"
                )
        dialog.destroy()

    def on_install_local_package(self, _button=None) -> None:
        lang = self.preferences.language
        dialog = Gtk.FileChooserDialog(
            title=t(lang, "install_package_title"),
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            t(lang, "password_cancel"),
            Gtk.ResponseType.CANCEL,
            t(lang, "password_continue"),
            Gtk.ResponseType.OK,
        )

        filter_all = Gtk.FileFilter()
        filter_all.set_name(t(lang, "package_filter_supported"))
        for ext in (
            "*.deb",
            "*.AppImage",
            "*.appimage",
            "*.tar.gz",
            "*.tgz",
            "*.tar.xz",
            "*.txz",
            "*.tar.bz2",
            "*.tbz2",
            "*.zip",
            "*.flatpak",
            "*.flatpakref",
            "*.rpm",
        ):
            filter_all.add_pattern(ext)
        dialog.add_filter(filter_all)

        filter_deb = Gtk.FileFilter()
        filter_deb.set_name(t(lang, "package_filter_deb"))
        filter_deb.add_pattern("*.deb")
        dialog.add_filter(filter_deb)

        filter_ai = Gtk.FileFilter()
        filter_ai.set_name(t(lang, "package_filter_appimage"))
        filter_ai.add_pattern("*.AppImage")
        filter_ai.add_pattern("*.appimage")
        dialog.add_filter(filter_ai)

        filter_arc = Gtk.FileFilter()
        filter_arc.set_name(t(lang, "package_filter_archive"))
        for ext in ("*.tar.gz", "*.tgz", "*.tar.xz", "*.txz", "*.tar.bz2", "*.tbz2", "*.zip"):
            filter_arc.add_pattern(ext)
        dialog.add_filter(filter_arc)

        filter_fp = Gtk.FileFilter()
        filter_fp.set_name(t(lang, "package_filter_flatpak"))
        filter_fp.add_pattern("*.flatpak")
        filter_fp.add_pattern("*.flatpakref")
        dialog.add_filter(filter_fp)

        filter_rpm = Gtk.FileFilter()
        filter_rpm.set_name(t(lang, "package_filter_rpm"))
        filter_rpm.add_pattern("*.rpm")
        dialog.add_filter(filter_rpm)

        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            dialog.destroy()
            if filename:
                self.prompt_and_install_file(filename)
        else:
            dialog.destroy()

    def prompt_and_install_file(self, filename: str, on_finished: Callable[[], None] | None = None) -> None:
        lang = self.preferences.language
        finish_callback = on_finished or self.reload_applications_async
        loading = Gtk.Dialog(
            title=t(lang, "package_inspecting"), transient_for=self, modal=True, destroy_with_parent=True
        )
        make_window_movable(loading)
        loading.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        loading._closed = False
        loading.connect("destroy", lambda widget: setattr(widget, "_closed", True))
        loading.connect("response", lambda widget, _response: widget.destroy())
        spinner = Gtk.Spinner()
        spinner.start()
        loading.get_content_area().pack_start(spinner, False, False, 12)
        filename_label = Gtk.Label(label=Path(filename).name)
        filename_label.set_line_wrap(True)
        filename_label.set_max_width_chars(48)
        loading.get_content_area().pack_start(filename_label, False, False, 12)
        loading.show_all()

        def finish(registry, info, status, error):
            if loading._closed:
                return False
            loading.destroy()
            if error:
                self._show_error_dialog(f"{t(lang, 'package_inspect_failed')}: {error}")
            else:
                dialog = PackageInstallerDialog(
                    parent=self,
                    info=info,
                    language=lang,
                    pkg_status=status,
                    registry=registry,
                    on_finished=finish_callback,
                )
                dialog.show_all()
            return False

        def worker():
            from sourcedock.backend.manager import ApplicationRegistry

            try:
                registry = ApplicationRegistry(distro_info=self.application_registry.distro)
                info = registry.inspect_local_package(filename)
                status = registry.get_local_package_status(info)
                GLib.idle_add(finish, registry, info, status, None)
            except Exception as exc:
                GLib.idle_add(finish, None, None, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_add_appimage(self, _button) -> None:
        self.on_install_local_package(_button)

    def on_bulk_remove_applications(self, _button) -> None:
        lang = self.preferences.language
        sel = self.applications_tree.get_selection()
        model, paths = sel.get_selected_rows()
        selected_apps = [model.get_value(model.get_iter(p), _AC_APP) for p in paths]
        selected_apps = [app for app in selected_apps if app.source != SOURCE_FIRMWARE]
        if not selected_apps:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
            type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=t(lang, "bulk_remove_title").format(count=len(selected_apps)),
        )
        make_window_movable(dialog)
        dialog.get_style_context().add_class("icon-settings-window")
        dialog.format_secondary_text("\n".join(f"{app.name} ({app.source.upper()})" for app in selected_apps))
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = dialog.add_button(t(lang, "applications_remove_selected"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")
        add_sensitive_removal_confirmation(dialog.get_content_area(), del_btn, selected_apps, lang)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.destroy()
            completed = set()

            def worker():
                failures = []
                for app in selected_apps:
                    if app.id in completed:
                        continue
                    try:
                        self.application_registry.remove(app)
                        completed.add(app.id)
                    except AuthRequiredError:
                        raise
                    except Exception as exc:
                        failures.append(f"{app.name}: {exc}")
                if failures:
                    GLib.idle_add(self.reload_applications_async)
                    raise BackendError("\n".join(failures))

            self._run_application_task(
                "bulk-remove",
                worker,
                "applications_remove_done",
                "applications_progress_remove",
                True,
                t(lang, "bulk_remove_title", count=len(selected_apps)),
            )
        else:
            dialog.destroy()

    def on_flatpak_permissions(self, _button, application: UnifiedApplication) -> None:
        load_dialog_data(
            self, t(self.preferences.language, "permissions_title", name=application.name),
            lambda: self.application_registry.flatpak_permissions(application.package_name),
            lambda permissions: self._show_flatpak_permissions(application, permissions),
        )

    def _show_flatpak_permissions(self, application, perms):
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "permissions_title").format(name=application.name),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=500, height=350)
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

        box = dialog.get_content_area()
        scroller = Gtk.ScrolledWindow()
        tv = Gtk.TextView()
        tv.set_editable(False)
        lines = []
        for sec, items in perms.items():
            lines.append(f"[{sec}]")
            lines.extend(f"  {it}" for it in items)
        tv.get_buffer().set_text("\n".join(lines) or t(lang, "permissions_none"))
        scroller.add(tv)
        box.pack_start(scroller, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_flatpak_rollback(self, _button, application: UnifiedApplication) -> None:
        load_dialog_data(
            self, t(self.preferences.language, "rollback_title", name=application.name),
            lambda: self.application_registry.flatpak_history(application.package_name),
            lambda history: self._show_flatpak_rollback(application, history),
        )

    def _show_flatpak_rollback(self, application, history):
        lang = self.preferences.language
        if not history:
            self._show_error_dialog(t(lang, "rollback_no_history"))
            return
        dialog = Gtk.Dialog(
            title=t(lang, "rollback_title").format(name=application.name),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=480, height=320)
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        rb_btn = dialog.add_button(t(lang, "rollback_btn"), Gtk.ResponseType.OK)
        rb_btn.get_style_context().add_class("suggested-action")

        combo = Gtk.ComboBoxText()
        for item in history:
            combo.append(
                item["commit"], f"{item.get('version', '')} - {item.get('date', '')} ({item['commit'][:8]})"
            )
        combo.set_active(0)
        dialog.get_content_area().pack_start(combo, False, False, 12)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            commit = combo.get_active_id()
            dialog.destroy()
            if commit:
                self._run_application_task(
                    action_name="rollback",
                    worker_callable=lambda: self.application_registry.flatpak_rollback(
                        application.package_name, commit
                    ),
                    success_message_key="applications_update_done",
                    progress_title_key="applications_progress_update",
                    refresh_after=True,
                )
        else:
            dialog.destroy()

    def on_show_changelog(self, _button, application: UnifiedApplication) -> None:
        self._on_package_changelog(application.package_name)
