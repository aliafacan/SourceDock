#!/usr/bin/env python3
"""Yüklü uygulamalar görünümü ve aksiyonları (InstalledViewMixin)."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import threading

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from voltapp.core.errors import AuthRequiredError, BackendError
from voltapp.core.models import (
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    ApplicationIssue,
    ApplicationSnapshot,
    UnifiedApplication,
)
from voltapp.i18n import t, translate_backend_message
from voltapp.ui.components.progress import OperationProgressWindow

_AC_ICON = 0
_AC_NAME = 1
_AC_SOURCE = 2
_AC_VERSION = 3
_AC_SIZE_KIB = 4
_AC_SIZE_STR = 5
_AC_LAST_UPDATED = 6
_AC_LOCATION = 7
_AC_APP = 8


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

        self.applications_add_appimage_btn = Gtk.Button()
        self.applications_add_appimage_btn.connect("clicked", self.on_add_appimage)
        search_row.pack_start(self.applications_add_appimage_btn, False, False, 0)

        filter_outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_outer.set_valign(Gtk.Align.CENTER)
        toolbar.pack_start(filter_outer, False, False, 0)

        for source in ("all", "updates", SOURCE_APT, SOURCE_FLATPAK, SOURCE_SNAP, SOURCE_APPIMAGE):
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_application_filter_toggled, source)
            filter_outer.pack_start(button, False, False, 0)
            self.application_filter_buttons[source] = button

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(6)
        sep.set_margin_end(6)
        filter_outer.pack_start(sep, False, False, 0)

        self.applications_category_label = Gtk.Label()
        self.applications_category_label.set_valign(Gtk.Align.CENTER)
        self.applications_category_label.get_style_context().add_class("dim-label")
        filter_outer.pack_start(self.applications_category_label, False, False, 0)

        self.applications_category_combo = Gtk.ComboBoxText()
        self.applications_category_combo.set_valign(Gtk.Align.CENTER)
        self.applications_category_combo.set_size_request(150, -1)
        self.applications_category_combo.append("__all__", "")
        self.applications_category_combo.connect("changed", self._on_category_filter_changed)
        filter_outer.pack_start(self.applications_category_combo, False, False, 0)

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
            GObject.TYPE_PYOBJECT,
        )
        self.applications_tree = Gtk.TreeView(model=self.applications_store)
        self.applications_tree.set_headers_visible(True)
        self.applications_tree.set_activate_on_single_click(False)
        self.applications_tree.set_enable_search(False)
        self.applications_tree.set_rubber_banding(False)
        self.applications_tree.get_style_context().add_class("applications-tree")
        self.applications_tree.connect("row-activated", self.on_application_tree_activated)
        self.applications_tree.connect("button-press-event", self.on_application_tree_button_press)

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
        version_col.set_fixed_width(100)
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

        date_renderer = Gtk.CellRendererText()
        date_col = Gtk.TreeViewColumn()
        self.applications_tree_col_date = date_col
        date_col.pack_start(date_renderer, True)
        date_col.add_attribute(date_renderer, "text", _AC_LAST_UPDATED)
        date_col.set_sort_column_id(_AC_LAST_UPDATED)
        date_col.set_resizable(True)
        date_col.set_fixed_width(130)
        self.applications_tree.append_column(date_col)

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

        apps_scroller = Gtk.ScrolledWindow()
        apps_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        apps_scroller.add(self.applications_tree)
        container.pack_start(apps_scroller, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.applications_launch_btn = Gtk.Button()
        self.applications_launch_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_launch_application))
        action_bar.pack_start(self.applications_launch_btn, False, False, 0)

        self.applications_action_update_btn = Gtk.Button()
        self.applications_action_update_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_update_application))
        action_bar.pack_start(self.applications_action_update_btn, False, False, 0)

        self.applications_action_location_btn = Gtk.Button()
        self.applications_action_location_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_open_application_location))
        action_bar.pack_start(self.applications_action_location_btn, False, False, 0)

        self.applications_permissions_btn = Gtk.Button()
        self.applications_permissions_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_permissions))
        action_bar.pack_start(self.applications_permissions_btn, False, False, 0)

        self.applications_rollback_btn = Gtk.Button()
        self.applications_rollback_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_rollback))
        action_bar.pack_start(self.applications_rollback_btn, False, False, 0)

        self.applications_changelog_btn = Gtk.Button()
        self.applications_changelog_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_show_changelog))
        action_bar.pack_start(self.applications_changelog_btn, False, False, 0)

        self.applications_action_remove_btn = Gtk.Button()
        self.applications_action_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_action_remove_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_remove_application))
        action_bar.pack_start(self.applications_action_remove_btn, False, False, 0)

        self.applications_bulk_remove_btn = Gtk.Button()
        self.applications_bulk_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_bulk_remove_btn.connect("clicked", self.on_bulk_remove_applications)
        action_bar.pack_start(self.applications_bulk_remove_btn, False, False, 0)

        self.applications_export_selected_btn = Gtk.Button()
        self.applications_export_selected_btn.connect("clicked", self._on_export_selected_applications)
        self.applications_export_selected_btn.set_sensitive(False)
        action_bar.pack_start(self.applications_export_selected_btn, False, False, 0)

        for btn in (
            self.applications_launch_btn,
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
        self._render_applications_list()

    def on_reload_applications(self, *_args) -> None:
        self.reload_applications_async()

    def on_flatpak_cleanup(self, *_args) -> None:
        self._run_application_task(
            action_name="flatpak_cleanup",
            worker_callable=self.application_registry.flatpak_cleanup,
            success_message_key="applications_flatpak_cleanup_done",
            progress_title_key="applications_flatpak_cleanup",
            refresh_after=False,
        )

    def on_check_for_updates(self, *_args) -> None:
        self._run_application_task(
            action_name="check_updates",
            worker_callable=self.application_registry.refresh_update_cache,
            success_message_key="applications_updates_checked",
            progress_title_key="applications_progress_check",
            refresh_after=True,
        )

    def on_update_all_applications(self, _button: Gtk.Button) -> None:
        updateable = [item for item in self.applications if item.update_available]
        if not updateable:
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
        self.on_launch_application(None, application)

    def on_application_tree_button_press(self, _tree: Gtk.TreeView, event) -> bool:
        if event.button == 3:
            path_info = self.applications_tree.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                path = path_info[0]
                model = self.applications_store
                it = model.get_iter(path)
                application: UnifiedApplication = model.get_value(it, _AC_APP)
                self._show_application_context_menu(application, event)
                return True
        return False

    def on_application_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        count = len(paths)
        if count == 0:
            for btn in (
                self.applications_launch_btn,
                self.applications_action_update_btn,
                self.applications_action_location_btn,
                self.applications_action_remove_btn,
                self.applications_permissions_btn,
                self.applications_rollback_btn,
                self.applications_changelog_btn,
                self.applications_export_selected_btn,
            ):
                btn.set_sensitive(False)
            return

        self.applications_export_selected_btn.set_sensitive(True)
        if count == 1:
            it = model.get_iter(paths[0])
            application: UnifiedApplication = model.get_value(it, _AC_APP)
            self.applications_launch_btn.set_sensitive(bool(application.executable))
            self.applications_action_update_btn.set_sensitive(application.update_available)
            self.applications_action_location_btn.set_sensitive(bool(application.install_path or application.desktop_file))
            self.applications_action_remove_btn.set_sensitive(True)
            is_flatpak = application.source == SOURCE_FLATPAK
            self.applications_permissions_btn.set_sensitive(is_flatpak)
            self.applications_rollback_btn.set_sensitive(is_flatpak)
            self.applications_changelog_btn.set_sensitive(application.source == SOURCE_APT)
        else:
            self.applications_launch_btn.set_sensitive(False)
            self.applications_action_location_btn.set_sensitive(False)
            self.applications_permissions_btn.set_sensitive(False)
            self.applications_rollback_btn.set_sensitive(False)
            self.applications_changelog_btn.set_sensitive(False)
            selected_apps = [model.get_value(model.get_iter(p), _AC_APP) for p in paths]
            self.applications_action_update_btn.set_sensitive(any(a.update_available for a in selected_apps))
            self.applications_action_remove_btn.set_sensitive(True)

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
        item_launch = Gtk.MenuItem(label=t(self.preferences.language, "applications_launch"))
        item_launch.connect("activate", lambda _: self.on_launch_application(None, application))
        menu.append(item_launch)

        if application.update_available:
            item_up = Gtk.MenuItem(label=t(self.preferences.language, "applications_update"))
            item_up.connect("activate", lambda _: self.on_update_application(None, application))
            menu.append(item_up)

        item_loc = Gtk.MenuItem(label=t(self.preferences.language, "applications_open_location"))
        item_loc.connect("activate", lambda _: self.on_open_application_location(None, application))
        menu.append(item_loc)

        item_del = Gtk.MenuItem(label=t(self.preferences.language, "applications_remove"))
        item_del.connect("activate", lambda _: self.on_remove_application(None, application))
        menu.append(item_del)

        menu.show_all()
        menu.popup_at_pointer(event)

    def on_launch_application(self, _button, application: UnifiedApplication) -> None:
        try:
            self.application_registry.launch(application)
        except BackendError as exc:
            self._set_applications_status(self._application_error_message(str(exc)), "red")

    def on_update_application(self, _button, application: UnifiedApplication) -> None:
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
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=t(self.preferences.language, "applications_remove_confirm_title"),
        )
        dialog.format_secondary_text(
            t(self.preferences.language, "applications_remove_confirm_body", name=application.name)
        )
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = dialog.add_button(t(self.preferences.language, "applications_remove"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")

        content = dialog.get_content_area()
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
        self.applications_loading = True
        self._set_application_controls_sensitive(False)
        self._set_applications_status(t(self.preferences.language, "applications_loading"), "#666666")
        threading.Thread(target=self._load_applications_worker, daemon=True).start()

    def _load_applications_worker(self) -> None:
        snapshot = self.application_registry.load()
        GLib.idle_add(self._finish_applications_load, snapshot)

    def _finish_applications_load(self, snapshot: ApplicationSnapshot) -> bool:
        self.applications = snapshot.applications
        self.application_issues = snapshot.issues
        self.application_provider_errors = snapshot.provider_errors
        self.installed_package_ids = {
            app.package_name for app in self.applications if app.package_name
        } | {app.name.lower() for app in self.applications}

        self.applications_loading = False
        self._set_application_controls_sensitive(True)
        self._update_category_combo()
        self._render_applications_list()
        self._render_application_diagnostics()

        update_count = sum(1 for item in self.applications if item.update_available)
        self.applications_update_all_btn.set_sensitive(update_count > 0)
        status_msg = t(self.preferences.language, "applications_loaded")
        if self.application_provider_errors:
            status_msg = t(self.preferences.language, "applications_load_partial")
        self._set_applications_status(status_msg, "#666666")
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
        self.applications_busy = True
        self._set_application_controls_sensitive(False)
        self._set_applications_status(t(self.preferences.language, "store_action_running"), "#666666")

        lang = self.preferences.language
        self._active_op_seq += 1
        op_key = f"app_{self._active_op_seq}"
        self._register_active_op(
            op_key, f"app {action_name}", progress_message or action_name, None,
            cancel_fn=self.application_registry.runner.cancel_current,
        )

        progress_dialog = OperationProgressWindow(
            title=t(lang, progress_title_key),
            message=progress_message,
            parent=self,
            on_progress=lambda f, lbl: self._update_op_row(op_key, f, lbl),
            language=lang,
        )
        self.application_registry.runner.set_output_callback(
            lambda line: GLib.idle_add(progress_dialog.append_log, line)
        )

        def worker():
            try:
                worker_callable()
            except AuthRequiredError as exc:
                self.application_registry.runner.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(
                    self._handle_application_auth_required,
                    exc, action_name, worker_callable, success_message_key,
                    progress_title_key, refresh_after, progress_message, retry,
                )
            except BackendError as exc:
                self.application_registry.runner.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                msg = self._application_error_message(str(exc))
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, False)
            except Exception as exc:
                self.application_registry.runner.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                msg = str(exc)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, False)
            else:
                self.application_registry.runner.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                msg = t(self.preferences.language, success_message_key)
                GLib.idle_add(progress_dialog.finish, True, msg)
                GLib.idle_add(self._finish_application_task, True, msg, refresh_after)

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
        password = self._ask_sudo_password(retry=retry or exc.password_failed)
        if password is None:
            self._finish_application_task(False, t(self.preferences.language, "status_cancelled"), False)
            return False
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
        if refresh_after and success:
            self.reload_applications_async()
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

    def _get_app_date_fallback(self, app: UnifiedApplication) -> str:
        if app.last_updated:
            return app.last_updated
        if app.desktop_file and os.path.isfile(app.desktop_file):
            try:
                mtime = os.path.getmtime(app.desktop_file)
                from datetime import datetime
                return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            except OSError:
                pass
        return "-"

    def _render_applications_list(self) -> None:
        if not hasattr(self, "applications_store") or self.applications_store is None:
            return
        self.applications_store.clear()
        filtered = self._filtered_application_items()
        self.filtered_applications = filtered

        for app in filtered:
            size_kib = self._get_app_size_fallback(app)
            date_str = self._get_app_date_fallback(app)
            self.applications_store.append([
                self._get_app_pixbuf(app),
                app.name,
                self._application_source_label(app.source),
                app.version or "-",
                size_kib or 0,
                self._format_application_size(size_kib),
                date_str,
                app.install_path or app.desktop_file or "-",
                app,
            ])
        total = len(self.applications)
        shown = len(filtered)
        self.applications_summary_label.set_text(
            t(self.preferences.language, "applications_count_summary", count=shown, total=total)
        )

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

    def _get_app_pixbuf(self, application: UnifiedApplication) -> GdkPixbuf.Pixbuf | None:
        cache_key = f"app:{application.id}"
        if cache_key in self._icon_pixbuf_cache:
            return self._icon_pixbuf_cache[cache_key]

        icon_name = application.icon
        if icon_name and os.path.exists(icon_name):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, 24, 24, True)
                if pb:
                    pb = self._scale_pixbuf_safe(pb, 24)
                self._icon_pixbuf_cache[cache_key] = pb
                return pb
            except Exception:
                pass

        theme = Gtk.IconTheme.get_default()
        for name in (icon_name, application.package_name, "application-x-executable"):
            if name and theme.has_icon(name):
                try:
                    pb = theme.load_icon(name, 24, Gtk.IconLookupFlags.FORCE_SIZE)
                    if pb:
                        pb = self._scale_pixbuf_safe(pb, 24)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        self._icon_pixbuf_cache[cache_key] = None
        return None

    def _render_application_diagnostics(self) -> None:
        for child in self.applications_diagnostics_list.get_children():
            self.applications_diagnostics_list.remove(child)

        all_notes = [f"⚠️ {err}" for err in self.application_provider_errors]
        for issue in self.application_issues:
            all_notes.append(f"• {issue.title}: {issue.detail}")

        if not all_notes:
            self.applications_diagnostics_label.set_text("Sorun tespit edilmedi.")
            return

        self.applications_diagnostics_label.set_text(f"{len(all_notes)} tanılama kaydı:")
        for note in all_notes[:10]:
            lbl = Gtk.Label(label=note)
            lbl.set_xalign(0)
            lbl.set_line_wrap(True)
            self.applications_diagnostics_list.add(lbl)
        self.applications_diagnostics_list.show_all()

    def _filtered_application_items(self) -> list[UnifiedApplication]:
        source = self.application_filter_source
        cat = self.application_filter_category
        query = self.application_search_text.lower()

        results = []
        for app in self.applications:
            if source == "updates" and not app.update_available:
                continue
            if source not in ("all", "updates") and app.source != source:
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
        self.applications_status.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(message)}</span>')

    def _application_source_label(self, source: str) -> str:
        lang = self.preferences.language
        if source == "all":
            return t(lang, "applications_source_all")
        if source == "updates":
            return t(lang, "applications_source_updates")
        return {
            SOURCE_APT: "APT",
            SOURCE_FLATPAK: "Flatpak",
            SOURCE_SNAP: "Snap",
            SOURCE_APPIMAGE: "AppImage",
        }.get(source, source)

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
            t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL,
            t(self.preferences.language, "settings_save"), Gtk.ResponseType.OK,
        )
        dialog.set_current_name("installed_applications.json")
        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            if filename:
                with open(filename, "w", encoding="utf-8") as fh:
                    fh.write(json_data)
                self._set_applications_status(f"{t(self.preferences.language, 'status_exported')}: {filename}", "#1f7a1f")
        dialog.destroy()

    def on_add_appimage(self, _button) -> None:
        lang = self.preferences.language
        dialog = Gtk.FileChooserDialog(
            title=t(lang, "add_appimage_title"),
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            t(lang, "password_cancel"), Gtk.ResponseType.CANCEL,
            t(lang, "add_appimage_btn"), Gtk.ResponseType.OK,
        )
        filter_ai = Gtk.FileFilter()
        filter_ai.set_name(t(lang, "appimage_files"))
        filter_ai.add_pattern("*.AppImage")
        filter_ai.add_pattern("*.appimage")
        dialog.add_filter(filter_ai)

        if dialog.run() == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            if filename:
                try:
                    self.application_registry.register_appimage(filename)
                    self.reload_applications_async()
                    self._set_applications_status(f"{t(lang, 'appimage_added')}: {Path(filename).name}", "#1f7a1f")
                except Exception as exc:
                    self._show_error_dialog(f"{t(lang, 'appimage_add_failed')}: {exc}")
        dialog.destroy()

    def on_bulk_remove_applications(self, _button) -> None:
        lang = self.preferences.language
        sel = self.applications_tree.get_selection()
        model, paths = sel.get_selected_rows()
        selected_apps = [model.get_value(model.get_iter(p), _AC_APP) for p in paths]
        if not selected_apps:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=t(lang, "bulk_remove_title").format(count=len(selected_apps)),
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = dialog.add_button(t(lang, "bulk_remove_btn"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")
        if dialog.run() == Gtk.ResponseType.OK:
            dialog.destroy()
            for app in selected_apps:
                try:
                    self.application_registry.remove(app)
                except Exception:
                    pass
            self.reload_applications_async()
        else:
            dialog.destroy()

    def on_flatpak_permissions(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        perms = self.application_registry.flatpak_permissions(application.package_name)
        dialog = Gtk.Dialog(
            title=t(lang, "permissions_title").format(name=application.name),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dialog.set_default_size(500, 350)
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
        lang = self.preferences.language
        history = self.application_registry.flatpak_history(application.package_name)
        if not history:
            self._show_error_dialog(t(lang, "rollback_no_history"))
            return
        dialog = Gtk.Dialog(
            title=t(lang, "rollback_title").format(name=application.name),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dialog.set_default_size(480, 320)
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        rb_btn = dialog.add_button(t(lang, "rollback_btn"), Gtk.ResponseType.OK)
        rb_btn.get_style_context().add_class("suggested-action")

        combo = Gtk.ComboBoxText()
        for item in history:
            combo.append(item["commit"], f"{item.get('version', '')} - {item.get('date', '')} ({item['commit'][:8]})")
        combo.set_active(0)
        dialog.get_content_area().pack_start(combo, False, False, 12)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            commit = combo.get_active_id()
            dialog.destroy()
            if commit:
                self._run_application_task(
                    action_name="rollback",
                    worker_callable=lambda: self.application_registry.flatpak_rollback(application.package_name, commit),
                    success_message_key="applications_update_done",
                    progress_title_key="applications_progress_update",
                    refresh_after=True,
                )
        else:
            dialog.destroy()

    def on_show_changelog(self, _button, application: UnifiedApplication) -> None:
        self._on_package_changelog(application.package_name)

