#!/usr/bin/env python3
"""Uygulama Mağazası (Store) arayüz görünümü ve mantığı."""

from __future__ import annotations

import threading
import re

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.errors import AuthRequiredError, BackendError, SnapClassicRequiredError
from sourcedock.core.icons import find_flatpak_icon_path, find_snap_icon_path
from sourcedock.core.models import (
    NATIVE_SOURCES,
    SOURCE_APT as STORE_APT,
    SOURCE_DNF as STORE_DNF,
    SOURCE_FLATPAK as STORE_FLATPAK,
    SOURCE_PACMAN as STORE_PACMAN,
    SOURCE_SNAP as STORE_SNAP,
    SOURCE_ZYPPER as STORE_ZYPPER,
    StoreResult,
    is_native_source,
)
from sourcedock.i18n import source_name, t, translate_provider_error
from sourcedock.theme import PALETTES, resolve_theme
from sourcedock.ui.components.dialogs import AppDetailDialog, show_snap_classic_dialog
from sourcedock.ui.components.progress import OperationProgressWindow
from sourcedock.ui.components.common import AppCard, ContentState, icon_button, set_status, style_tree_view

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
        self.store_search_entry.connect("search-changed", self._on_store_search_changed)
        self.store_search_entry.connect("activate", self.on_store_search)
        self.store_search_entry.set_no_show_all(True)
        self.store_search_entry.hide()
        search_row.pack_start(self.store_search_entry, True, True, 0)

        self.store_search_btn = Gtk.Button()
        self.store_search_btn.get_style_context().add_class("suggested-action")
        self.store_search_btn.connect("clicked", self.on_store_search)
        self.store_search_btn.set_no_show_all(True)
        self.store_search_btn.hide()
        search_row.pack_start(self.store_search_btn, False, False, 0)

        filter_row = Gtk.FlowBox()
        filter_row.set_selection_mode(Gtk.SelectionMode.NONE)
        filter_row.set_column_spacing(6)
        filter_row.set_row_spacing(6)
        filter_row.set_max_children_per_line(10)
        container.pack_start(filter_row, False, False, 0)

        self.store_search_status = Gtk.Label(xalign=0)
        self.store_search_status.get_style_context().add_class("dim-label")
        self.store_search_status.set_line_wrap(True)
        container.pack_start(self.store_search_status, False, False, 0)
        categories = Gtk.FlowBox()
        categories.set_selection_mode(Gtk.SelectionMode.NONE)
        categories.set_min_children_per_line(1)
        categories.set_max_children_per_line(5)
        categories.set_column_spacing(4)
        self.store_category_buttons = []
        for key, query in (
            ("productivity", "office"),
            ("development", "editor"),
            ("internet", "browser"),
            ("graphics", "graphics"),
            ("system", "system"),
        ):
            button = Gtk.ToggleButton(label=t(self.preferences.language, f"category_{key}"))
            button.get_style_context().add_class("filter-chip")
            button.set_tooltip_text(t(self.preferences.language, "store_category_shortcut"))
            button.connect("clicked", self._on_store_category, query)
            categories.add(button)
            self.store_category_buttons.append((button, key))
        container.pack_start(categories, False, False, 0)
        native_mgr = getattr(self.store_registry, "native_manager", STORE_APT)
        for source in ("all", STORE_FLATPAK, STORE_SNAP, native_mgr):
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_store_filter_toggled, source)
            filter_row.add(button)
            self.store_filter_buttons[source] = button

        self.store_installed_filter = Gtk.ToggleButton(
            label=t(self.preferences.language, "store_filter_installed")
        )
        self.store_installed_filter.get_style_context().add_class("filter-chip")
        self.store_installed_filter.set_tooltip_text(
            t(self.preferences.language, "tooltip_store_filter_installed")
        )
        self.store_installed_filter.get_accessible().set_name(
            t(self.preferences.language, "store_filter_installed")
        )
        self.store_installed_filter.connect("toggled", self._on_store_installed_filter_toggled)
        filter_row.add(self.store_installed_filter)
        self.store_installed_only = False

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
        style_tree_view(self.store_tree)
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
            cell.set_property("foreground", PALETTES[resolve_theme(self.preferences.theme)]["muted"])

        app_col.set_cell_data_func(name_rend, _name_cell_data)
        app_col.set_sort_column_id(_SC_NAME)
        app_col.set_resizable(True)
        app_col.set_expand(True)
        app_col.set_min_width(150)
        self.store_tree.append_column(app_col)
        self.store_tree.set_expander_column(app_col)

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
        version_col.set_min_width(110)
        version_col.set_fixed_width(120)
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
        self.store_cards = Gtk.FlowBox()
        self.store_cards.set_selection_mode(Gtk.SelectionMode.NONE)
        self.store_cards.set_homogeneous(True)
        self.store_cards.set_min_children_per_line(1)
        self.store_cards.set_max_children_per_line(3)
        self.store_cards.set_column_spacing(12)
        self.store_cards.set_row_spacing(12)
        self.store_cards.set_valign(Gtk.Align.START)
        cards_scroll = Gtk.ScrolledWindow()
        cards_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        cards_scroll.add(self.store_cards)
        self.store_view_stack = Gtk.Stack()
        self.store_view_stack.add_named(cards_scroll, "cards")
        self.store_view_stack.add_named(store_scroller, "table")
        self.store_state = ContentState(self.store_view_stack)
        container.pack_start(self.store_state, True, True, 0)
        self.store_layout_toggle = Gtk.ToggleButton()
        icon_button(
            self.store_layout_toggle, "view-list-symbolic", t(self.preferences.language, "table_details")
        )
        self.store_layout_toggle.connect(
            "toggled",
            lambda button: self.store_view_stack.set_visible_child_name(
                "table" if button.get_active() else "cards"
            ),
        )
        self.store_layout_toggle.connect(
            "toggled", lambda button: self.store_install_btn.set_visible(button.get_active())
        )
        search_row.pack_end(self.store_layout_toggle, False, False, 0)

        store_action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        store_action_bar.get_style_context().add_class("action-bar")
        container.pack_start(store_action_bar, False, False, 0)

        self.store_install_btn = Gtk.Button()
        self.store_install_btn.get_style_context().add_class("suggested-action")
        self.store_install_btn.connect("clicked", self.on_store_install)
        self.store_install_btn.set_sensitive(False)
        self.store_install_btn.set_no_show_all(True)
        store_action_bar.pack_start(self.store_install_btn, False, False, 0)

        self.store_status = Gtk.Label()
        self.store_status.set_xalign(0)
        self.store_status.set_line_wrap(True)
        self.store_status.set_no_show_all(True)
        self.store_status.hide()
        store_action_bar.pack_start(self.store_status, True, True, 0)

        self.store_filter_buttons["all"].set_active(True)
        self.store_state.show_state(
            t(self.preferences.language, "store_start"), t(self.preferences.language, "store_start_body")
        )

    def _on_store_category(self, _button, query):
        for button, _key in self.store_category_buttons:
            button.set_active(button.get_label() == _button.get_label())
        self.store_search_entry.set_text(query)
        self.header_search.set_text(query)
        self.on_store_search()

    def _on_store_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        """Debounce live discovery search so typing never starts one process per key."""
        if getattr(self, "_suppress_store_search_changed", False) or getattr(
            self, "_syncing_global_search", False
        ):
            return
        query = self.store_search_entry.get_text().strip()
        # The header search is the visible source of truth on Discover. Keep
        # programmatic captures and the hidden page entry on the same query.
        if self.header_search.get_text() != query:
            header_cursor = self.header_search.get_position()
            self._syncing_global_search = True
            try:
                self.header_search.set_text(query)
            finally:
                self._syncing_global_search = False
            self.header_search.set_position(min(header_cursor, len(query)))
        category_queries = {"office", "editor", "browser", "graphics", "system"}
        if query not in category_queries:
            for button, _key in self.store_category_buttons:
                button.set_active(False)
        if self._store_search_timeout_id:
            try:
                GLib.source_remove(self._store_search_timeout_id)
            except (TypeError, ValueError):
                pass
            self._store_search_timeout_id = 0
        if not query:
            self._store_search_generation += 1
            self.store_busy = False
            self.store_results = []
            self._render_store_results([])
            self.store_state.show_state(
                t(self.preferences.language, "store_start"),
                t(self.preferences.language, "store_start_body"),
            )
            self._set_store_status(t(self.preferences.language, "store_empty"), "#666666")
            return
        # Remote discovery is explicitly submitted with Enter. Starting a
        # provider request for every partially typed word makes the header
        # entry fight GTK's cursor position and creates stale partial results.
        # Keep the local empty-state reset above, but leave non-empty text idle
        # until the user submits it.

    def on_store_filter_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if not hasattr(self, "store_results_store") or self.store_results_store is None:
            return
        if not button.get_active():
            if not any(btn.get_active() for btn in self.store_filter_buttons.values()):
                button.set_active(True)
            return
        for src, btn in self.store_filter_buttons.items():
            if src != source:
                btn.set_active(False)
        self.store_filter_source = source
        self._render_store_results(self.store_results)

    def _on_store_installed_filter_toggled(self, button: Gtk.ToggleButton) -> None:
        self.store_installed_only = bool(button.get_active())
        if hasattr(self, "store_results_store") and self.store_results_store is not None:
            self._render_store_results(self.store_results)

    def on_store_search(self, *_args) -> None:
        if getattr(self, "_suppress_store_search", False):
            return
        query = self.header_search.get_text().strip() or self.store_search_entry.get_text().strip()
        if not query:
            return
        if self._store_search_timeout_id:
            try:
                GLib.source_remove(self._store_search_timeout_id)
            except (TypeError, ValueError):
                pass
            self._store_search_timeout_id = 0
        self._store_search_generation += 1
        generation = self._store_search_generation
        self.store_busy = True
        self.store_state.show_state(t(self.preferences.language, "store_searching"), loading=True)
        self.store_search_btn.set_sensitive(False)
        self.store_search_entry.set_sensitive(True)
        self._set_store_status(t(self.preferences.language, "store_searching"), "#666666")
        self.store_results_store.clear()

        def worker():
            try:
                sources = None if self.store_filter_source == "all" else {self.store_filter_source}
                published = False

                def publish(results, complete):
                    nonlocal published
                    published = True
                    GLib.idle_add(self._finish_store_search, results, None, generation, complete)

                results = self.store_registry.search(query, sources=sources, on_partial=publish)
                if not published:
                    GLib.idle_add(self._finish_store_search, results, None, generation, True)
            except BackendError as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc), generation, True)
            except Exception as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc), generation, True)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_store_search(
        self,
        results: list[StoreResult],
        error: str | None,
        generation: int | None = None,
        complete: bool = True,
    ) -> bool:
        if generation is not None and generation != self._store_search_generation:
            return False
        self.store_busy = not complete
        self.store_search_btn.set_sensitive(complete)
        self.store_search_entry.set_sensitive(True)
        if error:
            self.store_state.show_state(
                t(self.preferences.language, "store_error_title"),
                error,
                error=True,
                retry_callback=self.on_store_search,
                retry_label=t(self.preferences.language, "retry_action"),
            )
            self._set_store_status(error, "red")
            return False
        self.store_results = results
        self._render_store_results(results)
        visible_results = [result for result in results if result.is_application]
        if visible_results:
            self.store_state.show_content()
        elif complete:
            self.store_state.show_state(
                t(self.preferences.language, "store_no_results"),
                t(self.preferences.language, "store_applications_only")
                if results
                else t(self.preferences.language, "store_missing_providers")
                if getattr(self.store_registry, "missing_sources", [])
                else "",
            )
        if not complete:
            self._set_store_status(t(self.preferences.language, "store_results_partial"), "#666666")
            return False
        self.store_search_metrics = getattr(self.store_registry, "last_search_metrics", {})
        query = self.header_search.get_text().strip() or self.store_search_entry.get_text().strip()
        msg = t(self.preferences.language, "store_no_results")
        if visible_results:
            count = len(self._group_store_results(visible_results, query=query))
            msg = t(
                self.preferences.language,
                "store_results_for_query" if query else "store_recommended",
                query=query,
                count=count,
            )
        provenance = self._store_provenance_status()
        self._set_store_status(msg + (f"\n{provenance}" if provenance else ""), "#666666")
        if getattr(self.store_registry, "provider_errors", []):
            errors = []
            seen_errors = set()
            for error in self.store_registry.provider_errors:
                translated = translate_provider_error(self.preferences.language, error)
                key = translated.casefold()
                if key in seen_errors:
                    continue
                seen_errors.add(key)
                errors.append(translated)
            self._set_store_status(
                msg + (f"\n{provenance}" if provenance else "") + "\n" + "\n".join(errors),
                "red",
            )
        return False

    def on_store_result_selected(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        if it is None:
            self.store_install_btn.set_label(t(self.preferences.language, "store_install_btn"))
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
        if self.store_busy or self.applications_busy:
            return
        self.store_busy = True
        self.store_install_btn.set_sensitive(False)
        self._set_store_status(t(self.preferences.language, "store_action_running"), "#666666")

        if not retry and getattr(self, "_cached_sudo_password", None):
            self.store_registry.set_sudo_password(self._cached_sudo_password)

        lang = self.preferences.language
        self._active_op_seq += 1
        op_key = f"store_{self._active_op_seq}"
        remote = getattr(result, "remote", None) or "flathub"
        classic_flag = "--classic " if classic else ""
        op_cmd = f"{result.source} install {classic_flag}{remote} {result.app_id}"
        self._register_active_op(
            op_key,
            op_cmd,
            result.name,
            self._get_store_pixbuf(result),
            download_size=result.download_size_str or "",
            cancel_fn=self.store_registry.cancel_current,
        )

        progress_dialog = OperationProgressWindow(
            title=t(lang, "store_install_progress_title"),
            message=result.name,
            parent=self,
            on_progress=lambda f, lbl: self._update_op_row(op_key, f, lbl),
            language=lang,
            cancel_fn=self.store_registry.cancel_current,
        )
        self.store_registry.set_output_callback(lambda line: GLib.idle_add(progress_dialog.append_log, line))

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
                msg_key = apt_msg_key if is_native_source(result.source) else "store_password_message"
                retry_key = apt_retry_key if is_native_source(result.source) else "store_password_retry"
                GLib.idle_add(
                    self._handle_store_auth_required, result, exc, retry, msg_key, retry_key, classic
                )
            except BackendError as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key, False, msg)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            except Exception as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key, False, msg)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            else:
                self.store_registry.set_output_callback(None)
                msg = t(self.preferences.language, "store_install_done")
                GLib.idle_add(self._unregister_active_op, op_key, True, msg)
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
        self,
        result: StoreResult,
        exc: AuthRequiredError,
        retry: bool,
        message_key: str = "store_password_message",
        retry_key: str = "store_password_retry",
        classic: bool = False,
    ) -> bool:
        if retry or exc.password_failed:
            self._cached_sudo_password = None
        password = self._ask_sudo_password(
            retry=retry or exc.password_failed,
            message_key=message_key,
            retry_key=retry_key,
            operation=result.name,
        )
        if password is None:
            self._finish_store_install(False, t(self.preferences.language, "status_cancelled"))
            return False
        self._cached_sudo_password = password
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
        return f"{result.source}:{result.app_id}" in self.installed_package_ids

    def _group_store_results(
        self, results: list[StoreResult], query: str = ""
    ) -> list[tuple[StoreResult, list[StoreResult]]]:
        source_order = {
            STORE_FLATPAK: 0,
            STORE_SNAP: 1,
            STORE_APT: 2,
            STORE_DNF: 2,
            STORE_PACMAN: 2,
            STORE_ZYPPER: 2,
        }
        grouped: dict[str, list[StoreResult]] = {}
        normalized_query = query.strip().casefold()
        identity_aliases = {
            "firefox": "org.mozilla.firefox",
            "org.mozilla.firefox": "org.mozilla.firefox",
        }
        for r in results:
            # A provider may expose the same package id under several sources.
            # Keep one search card and let its details dialog choose the source.
            raw_identity = r.identity.casefold() if r.identity else ""
            raw_package = re.sub(r"[^a-z0-9.+:-]+", "", r.app_id.casefold())
            canonical = identity_aliases.get(raw_identity) or identity_aliases.get(raw_package)
            key = ("identity", canonical or raw_identity) if (canonical or raw_identity) else ("package", raw_package)
            grouped.setdefault(key, []).append(r)

        output: list[tuple[StoreResult, list[StoreResult]]] = []
        for _key, variants in grouped.items():
            def variant_relevance(result: StoreResult) -> tuple[int, int]:
                if normalized_query and result.app_id.casefold() == normalized_query:
                    rank = 0
                elif normalized_query and result.name.casefold() == normalized_query:
                    rank = 1
                elif normalized_query and (
                    result.app_id.casefold().startswith(normalized_query)
                    or result.name.casefold().startswith(normalized_query)
                ):
                    rank = 2
                else:
                    rank = 3
                return rank, source_order.get(result.source, 9)

            sorted_variants = sorted(variants, key=variant_relevance)
            primary = sorted_variants[0]
            children = sorted_variants[1:]
            output.append((primary, children))

        def relevance(group: tuple[StoreResult, list[StoreResult]]) -> tuple[int, str]:
            primary = group[0]
            variants = (primary, *group[1])
            names = [variant.name.casefold() for variant in variants if variant.name]
            app_ids = [variant.app_id.casefold() for variant in variants if variant.app_id]
            metadata = [
                value.casefold()
                for variant in variants
                for value in (variant.category, variant.description)
                if value
            ]
            if normalized_query and normalized_query in app_ids:
                rank = 0
            elif normalized_query and normalized_query in names:
                rank = 1
            elif normalized_query and any(
                value.startswith(normalized_query) for value in (*app_ids, *names)
            ):
                rank = 2
            elif normalized_query and any(normalized_query in value for value in metadata):
                rank = 3
            else:
                rank = 4
            return rank, primary.name.casefold()

        return sorted(output, key=relevance)

    def _render_store_results(self, results: list[StoreResult]) -> None:
        if not hasattr(self, "store_results_store") or self.store_results_store is None:
            return
        self.store_results_store.clear()
        for child in self.store_cards.get_children():
            self.store_cards.remove(child)
        filtered = [
            r
            for r in results
            if r.is_application
            and (not getattr(self, "store_installed_only", False) or self._store_result_is_installed(r))
            and (
                self.store_filter_source == "all"
                or r.source == self.store_filter_source
                or (self.store_filter_source in NATIVE_SOURCES and r.source in NATIVE_SOURCES)
            )
        ]
        groups = self._group_store_results(filtered, query=self.store_search_entry.get_text())
        source_states = getattr(self.store_registry, "last_search_source_states", {})
        for primary, children in groups:
            card_pixbuf = self._get_store_pixbuf(primary, 48)
            self.store_cards.add(
                AppCard(
                    primary,
                    card_pixbuf,
                    self._store_result_is_installed(primary),
                    self._open_store_detail_dialog,
                    self.preferences.language,
                    children,
                    source_states,
                )
            )
            p_pixbuf = self._get_store_pixbuf(primary, 32)
            name_label = primary.name
            if children:
                name_label = f"{primary.name}  (+{len(children)})"

            p_iter = self.store_results_store.append(
                None,
                [
                    p_pixbuf,
                    name_label,
                    self._display_store_source(primary),
                    primary.description,
                    primary.version,
                    primary.remote,
                    primary.download_size_str,
                    primary,
                ],
            )
            for child in children:
                c_pixbuf = self._get_store_pixbuf(child, 32)
                self.store_results_store.append(
                    p_iter,
                    [
                        c_pixbuf,
                        child.name,
                        self._display_store_source(child),
                        child.description,
                        child.version,
                        child.remote,
                        child.download_size_str,
                        child,
                    ],
                )
        self.store_cards.show_all()

    def _scale_pixbuf_safe(self, pb: GdkPixbuf.Pixbuf | None, size: int = 48) -> GdkPixbuf.Pixbuf | None:
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

    def _get_store_pixbuf(self, result: StoreResult, size: int = 48) -> GdkPixbuf.Pixbuf | None:
        cache_key = f"store:{result.source}:{result.remote}:{result.app_id}:{size}"
        if cache_key in self._icon_pixbuf_cache:
            return self._icon_pixbuf_cache[cache_key]
        if result.icon_path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(result.icon_path, size, size, True)
                if pb:
                    pb = self._scale_pixbuf_safe(pb, size)
                self._icon_pixbuf_cache[cache_key] = pb
                return pb
            except Exception:
                pass
        if result.source == STORE_FLATPAK:
            flatpak_path = find_flatpak_icon_path(result.app_id, result.remote)
            if flatpak_path:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(flatpak_path, size, size, True)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        if result.source == STORE_SNAP:
            snap_path = find_snap_icon_path(result.app_id)
            if snap_path:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(snap_path, size, size, True)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        theme = Gtk.IconTheme.get_default()
        generic_names = {"application-x-executable", "application-x-executable-symbolic"}
        fallback_by_source = {
            STORE_FLATPAK: "package-x-generic",
            STORE_SNAP: "package-x-generic",
        }
        fallback_name = fallback_by_source.get(result.source, "package-x-generic")
        # A human name is not an icon ID. Resolving it through IconTheme can
        # silently borrow an unrelated application's icon, especially for
        # remote Snap results. Only use an exact provider ID, then a neutral
        # package fallback.
        candidates = [result.app_id] if result.app_id and result.app_id not in generic_names else []
        candidates.append(fallback_name)
        for icon_name in candidates:
            if theme.has_icon(icon_name):
                try:
                    pb = theme.load_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    if pb:
                        pb = self._scale_pixbuf_safe(pb, size)
                    self._icon_pixbuf_cache[cache_key] = pb
                    return pb
                except Exception:
                    pass
        self._icon_pixbuf_cache[cache_key] = None
        return None

    def _display_store_source(self, result: StoreResult) -> str:
        label = source_name(self.preferences.language, result.source)
        state = getattr(self.store_registry, "last_search_source_states", {}).get(result.source)
        if state == "cached":
            return f"{label} · {t(self.preferences.language, 'store_source_cached_short')}"
        if state == "unavailable":
            return f"{label} · {t(self.preferences.language, 'store_source_unavailable_short')}"
        return label

    def _store_provenance_status(self) -> str:
        states = getattr(self.store_registry, "last_search_source_states", {})
        if not isinstance(states, dict) or not states:
            return ""
        groups = {"live": [], "cached": [], "unavailable": []}
        for source, state in states.items():
            groups.setdefault(state, []).append(source_name(self.preferences.language, source))
        lines = []
        if groups["live"] and (groups["cached"] or groups["unavailable"]):
            lines.append(t(self.preferences.language, "store_sources_live", sources=", ".join(groups["live"])))
        if groups["cached"]:
            lines.append(
                t(
                    self.preferences.language,
                    "store_sources_cached",
                    sources=", ".join(groups["cached"]),
                )
            )
        if groups["unavailable"]:
            lines.append(
                t(
                    self.preferences.language,
                    "store_sources_unavailable",
                    sources=", ".join(groups["unavailable"]),
                )
            )
        return "\n".join(lines)

    def _set_store_status(self, message: str, color: str) -> None:
        set_status(self.store_status, message, color == "red")
        if hasattr(self, "store_search_status"):
            set_status(self.store_search_status, message, color == "red")
