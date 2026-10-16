#!/usr/bin/env python3
"""Aktif süreçler ve paket işlemleri izleme görünümü."""

from __future__ import annotations

from datetime import datetime
import threading

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.i18n import t
from sourcedock.core.history import OperationHistory
from sourcedock.core.process import redact_text
from sourcedock.ui.components.common import ContentState, icon_button, style_tree_view

_OC_ICON = 0
_OC_PID = 1
_OC_COMMAND = 2
_OC_PACKAGES = 3


class OperationsViewMixin:
    """İşlemler (Operations) sekmesi kurulumu ve süreç yönetimi."""

    def _build_operations_page(self, container: Gtk.Box) -> None:
        self.operation_history = OperationHistory()
        self._external_operations = []
        self._external_operations_loading = False
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.operations_title_label = Gtk.Label(label="Aktif Paket İşlemleri")
        self.operations_title_label.set_xalign(0)
        title_box.pack_start(self.operations_title_label, True, True, 0)

        self.operations_refresh_btn = Gtk.Button(label="Yenile")
        self.operations_refresh_btn.connect("clicked", self._on_operations_refresh)
        title_box.pack_start(self.operations_refresh_btn, False, False, 0)
        container.pack_start(title_box, False, False, 0)

        self.operations_subtitle_label = Gtk.Label(
            label="Sistemde veya SourceDock içinde çalışan paket yönetim süreçlerini izle ve yönet."
        )
        self.operations_subtitle_label.set_xalign(0)
        self.operations_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.operations_subtitle_label, False, False, 0)

        self.operations_store = Gtk.ListStore(
            GdkPixbuf.Pixbuf,
            str,
            str,
            str,
            str,
        )
        self.operations_tree = Gtk.TreeView(model=self.operations_store)
        style_tree_view(self.operations_tree)
        self.operations_tree.set_headers_visible(True)

        sel = self.operations_tree.get_selection()
        sel.set_mode(Gtk.SelectionMode.SINGLE)
        sel.connect("changed", self._on_operations_selection_changed)

        self.operations_tree_col_process = Gtk.TreeViewColumn()
        self.operations_tree_col_process.set_title("İşlem")
        icon_rend = Gtk.CellRendererPixbuf()
        cmd_rend = Gtk.CellRendererText()
        cmd_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.operations_tree_col_process.pack_start(icon_rend, False)
        self.operations_tree_col_process.pack_start(cmd_rend, True)
        self.operations_tree_col_process.add_attribute(icon_rend, "pixbuf", _OC_ICON)
        self.operations_tree_col_process.add_attribute(cmd_rend, "text", _OC_COMMAND)
        self.operations_tree_col_process.set_expand(True)
        self.operations_tree.append_column(self.operations_tree_col_process)

        pid_rend = Gtk.CellRendererText()
        self.operations_tree_col_pid = Gtk.TreeViewColumn("PID", pid_rend, text=_OC_PID)
        self.operations_tree_col_pid.set_fixed_width(80)
        self.operations_tree_col_pid.set_visible(False)
        self.operations_tree.append_column(self.operations_tree_col_pid)

        pkg_rend = Gtk.CellRendererText()
        pkg_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.operations_tree_col_target = Gtk.TreeViewColumn("Hedef Paketler", pkg_rend, text=_OC_PACKAGES)
        self.operations_tree_col_target.set_expand(True)
        self.operations_tree.append_column(self.operations_tree_col_target)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.operations_tree)
        self.operations_state = ContentState(scroller)
        self.operations_state.show_state(
            t(self.preferences.language, "operations_empty"),
            t(self.preferences.language, "operations_empty_body"),
            icon_name="system-run-symbolic",
        )
        container.pack_start(self.operations_state, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.operations_pause_btn = Gtk.Button(label="Duraklat")
        self.operations_pause_btn.connect("clicked", self._on_operations_pause)
        self.operations_pause_btn.set_sensitive(False)
        self.operations_pause_btn.set_no_show_all(True)
        self.operations_pause_btn.hide()

        self.operations_cancel_btn = Gtk.Button(label="Görevi İptal Et")
        self.operations_cancel_btn.get_style_context().add_class("destructive-action")
        self.operations_cancel_btn.connect("clicked", self._on_operations_cancel)
        self.operations_cancel_btn.set_sensitive(False)
        self.operations_cancel_btn.set_no_show_all(True)
        self.operations_cancel_btn.hide()
        action_bar.pack_start(self.operations_cancel_btn, False, False, 0)
        self.operations_cancel_btn.set_tooltip_text(t(self.preferences.language, "cancel_critical"))
        history_expander = Gtk.Expander(label=t(self.preferences.language, "operation_history"))
        self.operations_history_expander = history_expander
        history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.history_store = Gtk.ListStore(str, str, str, str)
        history_tree = Gtk.TreeView(model=self.history_store)
        self.operations_history_columns = []
        for index, key in enumerate(
            ("operation_time", "operations_col_process", "applications_col_source", "operation_result")
        ):
            column = Gtk.TreeViewColumn(t(self.preferences.language, key), Gtk.CellRendererText(), text=index)
            column.set_resizable(True)
            history_tree.append_column(column)
            self.operations_history_columns.append((column, key))
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_min_content_height(120)
        history_scroll.set_max_content_height(200)
        history_scroll.add(history_tree)
        history_box.pack_start(history_scroll, True, True, 0)
        history_actions = Gtk.Box(spacing=8)
        export = Gtk.Button()
        self.operations_history_export_btn = export
        icon_button(
            export, "document-save-symbolic", t(self.preferences.language, "operation_history_export")
        )
        export.connect("clicked", self._on_history_export)
        clear = Gtk.Button()
        self.operations_history_clear_btn = clear
        icon_button(clear, "edit-clear-symbolic", t(self.preferences.language, "operation_history_clear"))
        clear.connect("clicked", self._on_history_clear)
        history_actions.pack_end(clear, False, False, 0)
        history_actions.pack_end(export, False, False, 0)
        history_box.pack_start(history_actions, False, False, 0)
        history_expander.add(history_box)
        container.pack_start(history_expander, False, False, 0)
        self._refresh_history()

    def _register_active_op(
        self,
        key: str,
        command: str,
        summary: str,
        pixbuf: GdkPixbuf.Pixbuf | None,
        download_size: str = "",
        cancel_fn=None,
    ) -> None:
        self._active_ops[key] = {
            "command": command,
            "base_summary": summary,
            "display_summary": summary,
            "pixbuf": pixbuf,
            "cancel_fn": cancel_fn,
        }
        self._refresh_operations_list()

    def _unregister_active_op(self, key: str, success=None, message="") -> None:
        operation = self._active_ops.pop(key, None)
        if operation and success is not None:
            try:
                self.operation_history.append(
                    operation["base_summary"], operation["command"], success, message
                )
                self._refresh_history()
            except OSError as exc:
                self._show_error_dialog(str(exc))
        self._refresh_operations_list()

    def _update_op_row(self, key: str, fraction: float, label: str) -> None:
        op = self._active_ops.get(key)
        if op:
            op["display_summary"] = f"{op['base_summary']} ({label})"
            self._refresh_operations_list()

    def _on_operations_refresh(self, *_args) -> None:
        self._refresh_operations_list()
        if self._external_operations_loading:
            return
        self._external_operations_loading = True

        def worker():
            try:
                holders = self.application_registry.runner._apt_lock_holders()
            except Exception:
                holders = []
            GLib.idle_add(self._finish_external_operations, holders)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_external_operations(self, holders):
        self._external_operations = holders
        self._external_operations_loading = False
        self._refresh_operations_list()
        return False

    def _refresh_operations_list(self) -> None:
        self.operations_store.clear()
        lang = self.preferences.language
        for key, op in self._active_ops.items():
            self.operations_store.append(
                [
                    op.get("pixbuf"),
                    "SourceDock",
                    op.get("display_summary", t(lang, "operations_in_progress")),
                    op.get("command", ""),
                    key,
                ]
            )
        for pid, args in self._external_operations:
            self.operations_store.append(
                [
                    None,
                    str(pid),
                    redact_text(args),
                    "APT / DPKG",
                    "",
                ]
            )
        has_operations = bool(self._active_ops or self._external_operations)
        if has_operations:
            self.operations_state.show_content()
        else:
            self.operations_state.show_state(
                t(lang, "operations_empty"),
                t(lang, "operations_empty_body"),
                icon_name="system-run-symbolic",
            )
        def can_cancel(op):
            cancel = op.get("cancel_fn")
            owner = getattr(cancel, "__self__", None)
            runner = getattr(owner, "_stream_runner", owner)
            return bool(cancel and getattr(runner, "_cancel_allowed", False))

        has_cancellable = any(can_cancel(op) for op in self._active_ops.values())
        self.operations_cancel_btn.set_visible(has_cancellable)
        self.operations_cancel_btn.set_sensitive(False)

    def _on_operations_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        key = model.get_value(it, 4) if it is not None else ""
        operation = self._active_ops.get(key, {})
        cancel = operation.get("cancel_fn")
        owner = getattr(cancel, "__self__", None)
        runner = getattr(owner, "_stream_runner", owner)
        self.operations_pause_btn.set_sensitive(False)
        self.operations_cancel_btn.set_sensitive(bool(cancel and getattr(runner, "_cancel_allowed", False)))

    def _on_operations_pause(self, *_args) -> None:
        return

    def _on_operations_cancel(self, *_args) -> None:
        sel = self.operations_tree.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        key = model.get_value(it, 4)
        cancel = self._active_ops.get(key, {}).get("cancel_fn")
        if cancel and not cancel():
            self._show_error_dialog(t(self.preferences.language, "cancel_critical"))
        self._refresh_operations_list()

    def _refresh_history(self):
        self.operations_history_expander.set_label(t(self.preferences.language, "operation_history"))
        for column, key in self.operations_history_columns:
            column.set_title(t(self.preferences.language, key))
        icon_button(
            self.operations_history_export_btn, "document-save-symbolic",
            t(self.preferences.language, "operation_history_export"),
        )
        icon_button(
            self.operations_history_clear_btn, "edit-clear-symbolic",
            t(self.preferences.language, "operation_history_clear"),
        )
        self.history_store.clear()
        for item in reversed(self.operation_history.load()):
            try:
                timestamp = datetime.fromisoformat(item["time"]).astimezone().strftime("%d.%m %H:%M")
            except (ValueError, KeyError):
                timestamp = "-"
            self.history_store.append(
                [
                    timestamp,
                    item.get("action", ""),
                    item.get("source", ""),
                    t(
                        self.preferences.language,
                        "operation_done" if item.get("success") else "operation_failed",
                    ),
                ]
            )

    def _on_history_clear(self, _button):
        self.operation_history.clear()
        self._refresh_history()

    def _on_history_export(self, _button):
        dialog = Gtk.FileChooserDialog(
            title=t(self.preferences.language, "operation_history_export"),
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            t(self.preferences.language, "password_cancel"),
            Gtk.ResponseType.CANCEL,
            t(self.preferences.language, "settings_save"),
            Gtk.ResponseType.OK,
        )
        dialog.set_current_name("sourcedock-history.json")
        dialog.set_do_overwrite_confirmation(True)
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                self.operation_history.export(dialog.get_filename())
            except OSError as exc:
                self._show_error_dialog(str(exc))
        dialog.destroy()
