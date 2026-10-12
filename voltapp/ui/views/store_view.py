#!/usr/bin/env python3
"""Uygulama Mağazası (Store) arayüz görünümü ve mantığı."""

from __future__ import annotations

import threading

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from voltapp.core.errors import AuthRequiredError, BackendError, SnapClassicRequiredError
from voltapp.core.models import (
    SOURCE_APT as STORE_APT,
    SOURCE_FLATPAK as STORE_FLATPAK,
    SOURCE_SNAP as STORE_SNAP,
    StoreResult,
)
from voltapp.i18n import t
from voltapp.ui.components.dialogs import AppDetailDialog, show_snap_classic_dialog
from voltapp.ui.components.progress import OperationProgressWindow

_SC_ICON = 0
_SC_NAME = 1
_SC_SOURCE = 2
_SC_DESCRIPTION = 3
_SC_VERSION = 4
_SC_REMOTE = 5
_SC_SIZE = 6
_SC_RESULT = 7


class StoreViewMixin:
    """Store sekmesi arayüz kurulumu ve işlem metotları."""

    def _build_store_page(self, container: Gtk.Box) -> None:
        self.store_title_label = Gtk.Label()
        self.store_title_label.set_xalign(0)
        container.pack_start(self.store_title_label, False, False, 0)

        self.store_subtitle_label = Gtk.Label()
        self.store_subtitle_label.set_xalign(0)
        self.store_subtitle_label.set_line_wrap(True)
        self.store_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.store_subtitle_label, False, False, 0)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.pack_start(search_row, False, False, 0)

        self.store_search_entry = Gtk.SearchEntry()
        self.store_search_entry.set_hexpand(True)
        self.store_search_entry.connect("activate", self.on_store_search)
        search_row.pack_start(self.store_search_entry, True, True, 0)

        self.store_search_btn = Gtk.Button()
        self.store_search_btn.get_style_context().add_class("suggested-action")
        self.store_search_btn.connect("clicked", self.on_store_search)
        search_row.pack_start(self.store_search_btn, False, False, 0)

        filter_row = Gtk.FlowBox()
        filter_row.set_selection_mode(Gtk.SelectionMode.NONE)
        filter_row.set_column_spacing(6)
        filter_row.set_row_spacing(6)
        filter_row.set_max_children_per_line(10)
        container.pack_start(filter_row, False, False, 0)
        for source in ("all", STORE_FLATPAK, STORE_SNAP, STORE_APT):
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_store_filter_toggled, source)
            filter_row.add(button)
            self.store_filter_buttons[source] = button
        self.store_filter_buttons["all"].set_active(True)

        self.store_results_store = Gtk.TreeStore(
            GdkPixbuf.Pixbuf,
            str,
            str,
            str,
            str,
            str,
            str,
            GObject.TYPE_PYOBJECT,
        )
        self.store_tree = Gtk.TreeView(model=self.store_results_store)
        self.store_tree.set_headers_visible(True)
        self.store_tree.set_enable_search(False)
        self.store_tree.set_rubber_banding(False)
        self.store_tree.set_show_expanders(True)
        self.store_tree.connect("row-activated", self.on_store_row_activated)

        store_sel = self.store_tree.get_selection()
        store_sel.set_mode(Gtk.SelectionMode.SINGLE)
        store_sel.connect("changed", self.on_store_result_selected)

        app_col = Gtk.TreeViewColumn()
        self.store_tree_col_name = app_col
        icon_rend = Gtk.CellRendererPixbuf()
        icon_rend.set_property("xpad", 4)
        name_rend = Gtk.CellRendererText()
        name_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        app_col.pack_start(icon_rend, False)
        app_col.pack_start(name_rend, True)
        app_col.add_attribute(icon_rend, "pixbuf", _SC_ICON)
        app_col.add_attribute(name_rend, "text", _SC_NAME)

        def _name_cell_data(_col, cell, model, it, _d):
            cell.set_property("style", Pango.Style.ITALIC if model.iter_parent(it) else Pango.Style.NORMAL)
            cell.set_property("foreground-set", bool(model.iter_parent(it)))
            cell.set_property("foreground", "#aaaaaa")

        app_col.set_cell_data_func(name_rend, _name_cell_data)
        app_col.set_sort_column_id(_SC_NAME)
        app_col.set_resizable(True)
        app_col.set_expand(True)
        app_col.set_min_width(150)
        self.store_tree.set_expander_column(app_col)
        self.store_tree.append_column(app_col)

        desc_renderer = Gtk.CellRendererText()
        desc_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        desc_col = Gtk.TreeViewColumn()
        self.store_tree_col_description = desc_col
        desc_col.pack_start(desc_renderer, True)
        desc_col.add_attribute(desc_renderer, "text", _SC_DESCRIPTION)
        desc_col.set_resizable(True)
        desc_col.set_expand(True)
        desc_col.set_min_width(150)
        self.store_tree.append_column(desc_col)

        source_renderer = Gtk.CellRendererText()
        source_col = Gtk.TreeViewColumn()
        self.store_tree_col_source = source_col
        source_col.pack_start(source_renderer, True)
        source_col.add_attribute(source_renderer, "text", _SC_SOURCE)
        source_col.set_sort_column_id(_SC_SOURCE)
        source_col.set_resizable(True)
        source_col.set_fixed_width(90)
        self.store_tree.append_column(source_col)

        version_renderer = Gtk.CellRendererText()
        version_col = Gtk.TreeViewColumn()
        self.store_tree_col_version = version_col
        version_col.pack_start(version_renderer, True)
        version_col.add_attribute(version_renderer, "text", _SC_VERSION)
        version_col.set_sort_column_id(_SC_VERSION)
        version_col.set_resizable(True)
        version_col.set_fixed_width(80)
        self.store_tree.append_column(version_col)

        size_renderer = Gtk.CellRendererText()
        size_col = Gtk.TreeViewColumn()
        self.store_tree_col_size = size_col
        size_col.pack_start(size_renderer, True)
        size_col.add_attribute(size_renderer, "text", _SC_SIZE)
        size_col.set_resizable(True)
        size_col.set_fixed_width(100)
        self.store_tree.append_column(size_col)

        store_scroller = Gtk.ScrolledWindow()
        store_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        store_scroller.add(self.store_tree)
        container.pack_start(store_scroller, True, True, 0)

        store_action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        store_action_bar.get_style_context().add_class("action-bar")
        container.pack_start(store_action_bar, False, False, 0)

        self.store_install_btn = Gtk.Button()
        self.store_install_btn.get_style_context().add_class("suggested-action")
        self.store_install_btn.connect("clicked", self.on_store_install)
        self.store_install_btn.set_sensitive(False)
        store_action_bar.pack_start(self.store_install_btn, False, False, 0)

        self.store_status = Gtk.Label()
        self.store_status.set_xalign(0)
        self.store_status.set_line_wrap(True)
        store_action_bar.pack_start(self.store_status, True, True, 0)

    def on_store_filter_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if not button.get_active():
            if not any(btn.get_active() for btn in self.store_filter_buttons.values()):
                button.set_active(True)
            return
        for src, btn in self.store_filter_buttons.items():
            if src != source:
                btn.set_active(False)
        self.store_filter_source = source
        self._render_store_results(self.store_results)

    def on_store_search(self, *_args) -> None:
        query = self.store_search_entry.get_text().strip()
        if not query:
            return
        self.store_busy = True
        self.store_search_btn.set_sensitive(False)
        self.store_search_entry.set_sensitive(False)
        self._set_store_status(t(self.preferences.language, "store_searching"), "#666666")
        self.store_results_store.clear()

        def worker():
            try:
                results = self.store_registry.search(query)
                GLib.idle_add(self._finish_store_search, results, None)
            except BackendError as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc))
            except Exception as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_store_search(self, results: list[StoreResult], error: str | None) -> bool:
        self.store_busy = False
        self.store_search_btn.set_sensitive(True)
        self.store_search_entry.set_sensitive(True)
        if error:
            self._set_store_status(error, "red")
            return False
        self.store_results = results
        self._render_store_results(results)
        msg = t(self.preferences.language, "store_no_results") if not results else f"{len(results)} sonuç bulundu."
        self._set_store_status(msg, "#666666")
        return False

    def on_store_result_selected(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        if it is None:
            self.store_install_btn.set_sensitive(False)
            return
        result: StoreResult = model.get_value(it, _SC_RESULT)
        is_installed = self._store_result_is_installed(result)
        self.store_install_btn.set_sensitive(not is_installed)
        if is_installed:
            self.store_install_btn.set_label(f"✓ {t(self.preferences.language, 'store_installed_badge')}")
        else:
            self.store_install_btn.set_label(t(self.preferences.language, "store_install_btn"))

    def on_store_row_activated(self, tree: Gtk.TreeView, path, _col) -> None:
        model = tree.get_model()
        it = model.get_iter(path)
        if it is None:
            return
        result: StoreResult = model.get_value(it, _SC_RESULT)
        self._open_store_detail_dialog(result)

    def _open_store_detail_dialog(self, result: StoreResult) -> None:
        AppDetailDialog(
            primary_result=result,
            all_results=self.store_results,
            installed_package_ids=self.installed_package_ids,
            install_callback=lambda res: self._run_store_install(res),
            language=self.preferences.language,
            parent=self,
        )

    def on_store_install(self, _button: Gtk.Button) -> None:
        if self.store_busy:
            return
        selection = self.store_tree.get_selection()
        model, it = selection.get_selected()
        if it is None:
            return
        result: StoreResult = model.get_value(it, _SC_RESULT)
        self._open_store_detail_dialog(result)

    def _run_store_install(self, result: StoreResult, retry: bool = False, classic: bool = False) -> None:
        self.store_busy = True
        self.store_install_btn.set_sensitive(False)
        self._set_store_status(t(self.preferences.language, "store_action_running"), "#666666")

        lang = self.preferences.language
        self._active_op_seq += 1
        op_key = f"store_{self._active_op_seq}"
        remote = getattr(result, "remote", None) or "flathub"
        classic_flag = "--classic " if classic else ""
        op_cmd = f"{result.source} install {classic_flag}{remote} {result.app_id}"
        self._register_active_op(
            op_key, op_cmd, result.name, self._get_store_pixbuf(result),
            download_size=result.download_size_str or "",
            cancel_fn=self.store_registry.cancel_current,
        )

        progress_dialog = OperationProgressWindow(
            title=t(lang, "store_install_progress_title"),
            message=result.name,
            parent=self,
            on_progress=lambda f, lbl: self._update_op_row(op_key, f, lbl),
            language=lang,
        )
        self.store_registry.set_output_callback(
            lambda line: GLib.idle_add(progress_dialog.append_log, line)
        )

        apt_msg_key = "store_apt_password_message"
        apt_retry_key = "store_apt_password_retry"

        def worker() -> None:
            try:
                self.store_registry.install(result, classic=classic)
            except SnapClassicRequiredError:
                self.store_registry.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(self._handle_snap_classic_required, result)
            except AuthRequiredError as exc:
                self.store_registry.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                msg_key = apt_msg_key if result.source == STORE_APT else "store_password_message"
                retry_key = apt_retry_key if result.source == STORE_APT else "store_password_retry"
                GLib.idle_add(self._handle_store_auth_required, result, exc, retry, msg_key, retry_key, classic)
            except BackendError as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            except Exception as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            else:
                self.store_registry.set_output_callback(None)
                msg = t(self.preferences.language, "store_install_done")
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, True, msg)
                GLib.idle_add(self._finish_store_install, True, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_snap_classic_required(self, result: StoreResult) -> bool:
        lang = self.preferences.language
        if show_snap_classic_dialog(self, lang, result.name):
            self.store_busy = False
            self._run_store_install(result, retry=True, classic=True)
        else:
            self._finish_store_install(False, t(lang, "status_cancelled"))
        return False

    def _handle_store_auth_required(
        self, result: StoreResult, exc: AuthRequiredError, retry: bool,
        message_key: str = "store_password_message",
        retry_key: str = "store_password_retry",
        classic: bool = False,
    ) -> bool:
        password = self._ask_sudo_password(
            retry=retry or exc.password_failed,
            message_key=message_key,
            retry_key=retry_key,
        )
        if password is None:
            self._finish_store_install(False, t(self.preferences.language, "status_cancelled"))
            return False
        self.store_registry.set_sudo_password(password)
        self.store_busy = False
        self._run_store_install(result, retry=True, classic=classic)
        return False

    def _finish_store_install(self, success: bool, message: str) -> bool:
        self.store_busy = False
        self._set_store_status(message, "#1f7a1f" if success else "red")
        if success:
            self.reload_applications_async()
        else:
            self.on_store_result_selected(self.store_tree.get_selection())
        return False

    def _store_result_is_installed(self, result: StoreResult) -> bool:
        return result.app_id in self.installed_package_ids or result.name.lower() in self.installed_package_ids

    def _group_store_results(
        self, results: list[StoreResult]
    ) -> list[tuple[StoreResult, list[StoreResult]]]:
        source_order = {STORE_FLATPAK: 0, STORE_SNAP: 1, STORE_APT: 2}
        grouped: dict[str, list[StoreResult]] = {}
        for r in results:
            key = r.name.strip().lower()
            grouped.setdefault(key, []).append(r)

        output: list[tuple[StoreResult, list[StoreResult]]] = []
        for _key, variants in grouped.items():
            sorted_variants = sorted(
                variants, key=lambda v: source_order.get(v.source, 9)
            )
            primary = sorted_variants[0]
            children = sorted_variants[1:]
            output.append((primary, children))
        return output

    def _render_store_results(self, results: list[StoreResult]) -> None:
        self.store_results_store.clear()
        filtered = [
            r for r in results
            if self.store_filter_source == "all" or r.source == self.store_filter_source
        ]
        groups = self._group_store_results(filtered)
        for primary, children in groups:
            p_pixbuf = self._get_store_pixbuf(primary)
            name_label = primary.name
            if children:
                name_label = f"{primary.name}  (+{len(children)})"

            p_iter = self.store_results_store.append(
                None,
                [
                    p_pixbuf,
                    name_label,
                    primary.source.capitalize(),
                    primary.description,
                    primary.version,
                    primary.remote,
                    primary.download_size_str,
                    primary,
                ],
            )
            for child in children:
                c_pixbuf = self._get_store_pixbuf(child)
                self.store_results_store.append(
                    p_iter,
                    [
                        c_pixbuf,
                        child.name,
                        child.source.capitalize(),
                        child.description,
                        child.version,
                        child.remote,
                        child.download_size_str,
                        child,
                    ],
                )

    def _get_store_pixbuf(self, result: StoreResult) -> GdkPixbuf.Pixbuf | None:
        cache_key = f"store:{result.source}:{result.app_id}"
        if cache_key in self._icon_pixbuf_cache:
            return self._icon_pixbuf_cache[cache_key]
        if result.icon_path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(result.icon_path, 24, 24, True)
                self._icon_pixbuf_cache[cache_key] = pb
                return pb
            except Exception:
                pass
        theme = Gtk.IconTheme.get_default()
        for icon_name in (result.app_id, result.name.lower(), "application-x-executable"):
            if theme.has_icon(icon_name):
                try:
                    pb = theme.load_icon(icon_name, 24, Gtk.IconLookupFlags.GENERIC_FALLBACK)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        self._icon_pixbuf_cache[cache_key] = None
        return None

    def _set_store_status(self, message: str, color: str) -> None:
        self.store_status.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(message)}</span>')

