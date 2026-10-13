#!/usr/bin/env python3
"""Sistem/APT paketleri listesi ve yönetimi görünümü."""

from __future__ import annotations

import threading

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from voltapp.core.errors import AuthRequiredError, BackendError
from voltapp.core.models import PackageInfo
from voltapp.i18n import t
from voltapp.ui.components.progress import OperationProgressWindow

_PC_NAME = 0
_PC_VERSION = 1
_PC_NEW_VERSION = 2
_PC_SIZE_KIB = 3
_PC_SIZE_STR = 4
_PC_DESCRIPTION = 5
_PC_UPGRADABLE = 6
_PC_PKG = 7


class PackagesViewMixin:
    """Paketler sekmesi arayüz kurulumu ve işlem metotları."""

    def _build_packages_page(self, container: Gtk.Box) -> None:
        self.packages_title_label = Gtk.Label()
        self.packages_title_label.set_xalign(0)
        container.pack_start(self.packages_title_label, False, False, 0)

        self.packages_subtitle_label = Gtk.Label()
        self.packages_subtitle_label.set_xalign(0)
        self.packages_subtitle_label.set_line_wrap(True)
        self.packages_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.packages_subtitle_label, False, False, 0)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.pack_start(search_row, False, False, 0)

        self.packages_search_entry = Gtk.SearchEntry()
        self.packages_search_entry.set_hexpand(True)
        self.packages_search_entry.connect("search-changed", self._on_packages_search_changed)
        search_row.pack_start(self.packages_search_entry, True, True, 0)

        self.packages_filter_all_btn = Gtk.ToggleButton()
        self.packages_filter_all_btn.get_style_context().add_class("filter-chip")
        self.packages_filter_all_btn.connect("toggled", self._on_packages_filter_all_toggled)
        search_row.pack_start(self.packages_filter_all_btn, False, False, 0)

        self.packages_filter_upgradable_btn = Gtk.ToggleButton()
        self.packages_filter_upgradable_btn.get_style_context().add_class("filter-chip")
        self.packages_filter_upgradable_btn.connect("toggled", self._on_packages_filter_upgradable_toggled)
        search_row.pack_start(self.packages_filter_upgradable_btn, False, False, 0)

        self.packages_refresh_btn = Gtk.Button()
        self.packages_refresh_btn.connect("clicked", self._on_packages_refresh)
        search_row.pack_start(self.packages_refresh_btn, False, False, 0)

        self.packages_store = Gtk.ListStore(
            str,
            str,
            str,
            int,
            str,
            str,
            bool,
            GObject.TYPE_PYOBJECT,
        )
        self.packages_tree = Gtk.TreeView(model=self.packages_store)
        self.packages_tree.set_headers_visible(True)
        self.packages_tree.set_rubber_banding(True)
        self.packages_tree.connect("button-press-event", self.on_packages_tree_button_press)

        pkg_sel = self.packages_tree.get_selection()
        pkg_sel.set_mode(Gtk.SelectionMode.MULTIPLE)
        pkg_sel.connect("changed", self._on_package_selection_changed)

        name_rend = Gtk.CellRendererText()
        name_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_name = Gtk.TreeViewColumn("Paket", name_rend, text=_PC_NAME)
        self.packages_tree_col_name.set_sort_column_id(_PC_NAME)
        self.packages_tree_col_name.set_resizable(True)
        self.packages_tree_col_name.set_expand(True)
        self.packages_tree_col_name.set_min_width(140)
        self.packages_tree.append_column(self.packages_tree_col_name)

        ver_rend = Gtk.CellRendererText()
        self.packages_tree_col_version = Gtk.TreeViewColumn("Sürüm", ver_rend, text=_PC_VERSION)
        self.packages_tree_col_version.set_sort_column_id(_PC_VERSION)
        self.packages_tree_col_version.set_resizable(True)
        self.packages_tree_col_version.set_fixed_width(110)
        self.packages_tree.append_column(self.packages_tree_col_version)

        up_rend = Gtk.CellRendererText()
        up_rend.set_property("foreground", "#59d38c")
        self.packages_tree_col_new_version = Gtk.TreeViewColumn("Yeni Sürüm", up_rend, text=_PC_NEW_VERSION)
        self.packages_tree_col_new_version.set_sort_column_id(_PC_NEW_VERSION)
        self.packages_tree_col_new_version.set_resizable(True)
        self.packages_tree_col_new_version.set_fixed_width(110)
        self.packages_tree.append_column(self.packages_tree_col_new_version)

        size_rend = Gtk.CellRendererText()
        self.packages_tree_col_size = Gtk.TreeViewColumn("Boyut", size_rend, text=_PC_SIZE_STR)
        self.packages_tree_col_size.set_sort_column_id(_PC_SIZE_KIB)
        self.packages_tree_col_size.set_resizable(True)
        self.packages_tree_col_size.set_fixed_width(80)
        self.packages_tree.append_column(self.packages_tree_col_size)

        desc_rend = Gtk.CellRendererText()
        desc_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_description = Gtk.TreeViewColumn("Açıklama", desc_rend, text=_PC_DESCRIPTION)
        self.packages_tree_col_description.set_resizable(True)
        self.packages_tree_col_description.set_expand(True)
        self.packages_tree_col_description.set_min_width(200)
        self.packages_tree.append_column(self.packages_tree_col_description)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.packages_tree)
        container.pack_start(scroller, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.packages_update_btn = Gtk.Button()
        self.packages_update_btn.get_style_context().add_class("suggested-action")
        self.packages_update_btn.connect("clicked", self._on_update_selected_packages)
        self.packages_update_btn.set_sensitive(False)
        action_bar.pack_start(self.packages_update_btn, False, False, 0)

        self.packages_update_all_btn = Gtk.Button()
        self.packages_update_all_btn.connect("clicked", self._on_update_all_packages)
        self.packages_update_all_btn.set_sensitive(False)
        action_bar.pack_start(self.packages_update_all_btn, False, False, 0)

        self.packages_status = Gtk.Label()
        self.packages_status.set_xalign(0)
        self.packages_status.set_line_wrap(True)
        action_bar.pack_start(self.packages_status, True, True, 0)

        self.packages_filter_all_btn.set_active(True)

    def reload_packages_async(self) -> None:
        if self.packages_loading:
            return
        self.packages_loading = True
        self.packages_refresh_btn.set_sensitive(False)
        self._set_packages_status("Paketler taranıyor...", "#666666")
        threading.Thread(target=self._load_packages_worker, daemon=True).start()

    def _load_packages_worker(self) -> None:
        try:
            packages = self.application_registry.list_packages()
            GLib.idle_add(self._finish_packages_load, packages, None)
        except Exception as exc:
            GLib.idle_add(self._finish_packages_load, [], str(exc))

    def _finish_packages_load(self, packages: list[PackageInfo], error: str | None) -> bool:
        self.packages_loading = False
        self.packages_refresh_btn.set_sensitive(True)
        if error:
            self._set_packages_status(error, "red")
            return False
        self.packages = packages
        self._render_packages_list()
        upgradable_count = sum(1 for p in packages if p.update_available)
        msg = f"{len(packages)} paket yüklü"
        if upgradable_count:
            msg += f" · {upgradable_count} güncellenebilir"
        self._set_packages_status(msg, "#666666")
        self.packages_update_all_btn.set_sensitive(upgradable_count > 0)
        return False

    def _render_packages_list(self) -> None:
        if not hasattr(self, "packages_store") or self.packages_store is None:
            return
        self.packages_store.clear()
        query = self.packages_search_text.lower()
        upgradable_only = self.packages_filter_upgradable

        for pkg in self.packages:
            if upgradable_only and not pkg.update_available:
                continue
            if query and query not in pkg.name.lower() and query not in pkg.description.lower():
                continue
            size_str = self._format_application_size(pkg.installed_size_kib)
            self.packages_store.append([
                pkg.name,
                pkg.version,
                pkg.new_version,
                pkg.installed_size_kib or 0,
                size_str,
                pkg.description,
                pkg.update_available,
                pkg,
            ])

    def _on_packages_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.packages_search_text = entry.get_text().strip()
        self._render_packages_list()

    def _on_packages_filter_all_toggled(self, button: Gtk.ToggleButton) -> None:
        if not hasattr(self, "packages_filter_upgradable_btn"):
            return
        if not button.get_active():
            if not self.packages_filter_upgradable_btn.get_active():
                button.set_active(True)
            return
        self.packages_filter_upgradable_btn.set_active(False)
        self.packages_filter_upgradable = False
        self._render_packages_list()

    def _on_packages_filter_upgradable_toggled(self, button: Gtk.ToggleButton) -> None:
        if not hasattr(self, "packages_filter_all_btn"):
            return
        if not button.get_active():
            if not self.packages_filter_all_btn.get_active():
                button.set_active(True)
            return
        self.packages_filter_all_btn.set_active(False)
        self.packages_filter_upgradable = True
        self._render_packages_list()

    def _on_packages_refresh(self, *_args) -> None:
        self.reload_packages_async()

    def on_packages_tree_button_press(self, _tree: Gtk.TreeView, event) -> bool:
        if event.button == 3:
            path_info = self.packages_tree.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                path = path_info[0]
                model = self.packages_store
                it = model.get_iter(path)
                pkg: PackageInfo = model.get_value(it, _PC_PKG)
                self._show_package_context_menu(pkg, event)
                return True
        return False

    def _show_package_context_menu(self, package: PackageInfo, event) -> None:
        menu = Gtk.Menu()
        if package.update_available:
            item_up = Gtk.MenuItem(label=f"Güncelle ({package.new_version})")
            item_up.connect("activate", lambda _: self._run_packages_task([package.name], "packages_update"))
            menu.append(item_up)

        item_log = Gtk.MenuItem(label="Değişiklik Günlüğü (Changelog)")
        item_log.connect("activate", lambda _: self._on_package_changelog(package.name))
        menu.append(item_log)

        menu.show_all()
        menu.popup_at_pointer(event)

    def _on_package_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        selected_pkgs = [model.get_value(model.get_iter(p), _PC_PKG) for p in paths]
        has_upgradable = any(p.update_available for p in selected_pkgs)
        self.packages_update_btn.set_sensitive(has_upgradable)

    def _on_update_selected_packages(self, *_args) -> None:
        sel = self.packages_tree.get_selection()
        model, paths = sel.get_selected_rows()
        names = [
            model.get_value(model.get_iter(p), _PC_PKG).name
            for p in paths
            if model.get_value(model.get_iter(p), _PC_PKG).update_available
        ]
        if names:
            self._run_packages_task(names, "packages_update")

    def _on_update_all_packages(self, *_args) -> None:
        names = [p.name for p in self.packages if p.update_available]
        if names:
            self._run_packages_task(names, "packages_update_all")

    def _on_package_changelog(self, package_name: str) -> None:
        lang = self.preferences.language
        text = self.application_registry.apt_changelog(package_name)
        dialog = Gtk.Dialog(
            title=t(lang, "changelog_title").format(name=package_name),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dialog.get_style_context().add_class("icon-settings-window")
        dialog.set_default_size(600, 400)
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

        scroller = Gtk.ScrolledWindow()
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        buf = tv.get_buffer()
        buf.set_text(text or t(lang, "changelog_none"))
        scroller.add(tv)
        dialog.get_content_area().pack_start(scroller, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _run_packages_task(self, names: list[str], title_key: str) -> None:
        lang = self.preferences.language
        progress_dialog = OperationProgressWindow(
            title=t(lang, title_key),
            message=f"{len(names)} {t(lang, 'progress_packages_unit')}",
            parent=self,
            language=lang,
        )
        self.application_registry.runner.set_output_callback(
            lambda line: GLib.idle_add(progress_dialog.append_log, line)
        )

        def worker():
            try:
                self.application_registry.update_packages(names)
                GLib.idle_add(progress_dialog.finish, True, t(lang, "packages_update_done"))
                GLib.idle_add(self.reload_packages_async)
            except AuthRequiredError:
                GLib.idle_add(progress_dialog.destroy)
                pwd = self._ask_sudo_password()
                if pwd:
                    self.application_registry.set_sudo_password(pwd)
                    self._run_packages_task(names, title_key)
            except Exception as exc:
                GLib.idle_add(progress_dialog.finish, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _set_packages_status(self, message: str, color: str) -> None:
        self.packages_status.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(message)}</span>')

