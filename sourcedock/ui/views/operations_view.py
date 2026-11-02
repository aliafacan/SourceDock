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
        action_bar.set_no_show_all(True)
        action_bar.hide()
        container.pack_start(action_bar, False, False, 0)
        self.operations_action_bar = action_bar

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

        def _sync_operations_action_bar_vis(*_args):
            action_bar.set_visible(self.operations_cancel_btn.get_visible())

        self.operations_cancel_btn.connect("notify::visible", _sync_operations_action_bar_vis)
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
        preview = Gtk.Button(label=t(self.preferences.language, "rollback_preview"))
        preview.connect("clicked", self._show_apt_rollback_preview)
        history_actions.pack_start(preview, False, False, 0)
        self._refresh_history()

    def _show_apt_rollback_preview(self, button):
        runners = (self.application_registry.runner, self.store_registry.runner)
        records = [(runner, record) for runner in runners
                   for record in getattr(runner, "apt_transactions", {}).values()]
        dialog = Gtk.Dialog(title=t(self.preferences.language, "rollback_preview"),
                            transient_for=self, modal=True)
        dialog.set_default_size(680, 440)
        dialog.add_button(t(self.preferences.language, "progress_close"), Gtk.ResponseType.CLOSE)
        box = dialog.get_content_area()
        note = Gtk.Label(label=t(self.preferences.language, "rollback_preview_only"), xalign=0)
        note.set_line_wrap(True)
        box.pack_start(note, False, False, 8)
        combo = Gtk.ComboBoxText()
        for index, (_runner, record) in enumerate(records):
            combo.append(str(index), f"{record.id[:8]}: {' '.join(record.command)}")
        box.pack_start(combo, False, False, 8)
        output = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.add(output)
        box.pack_start(scroll, True, True, 0)
        generation = [0]
        def changed(widget):
            generation[0] += 1
            token = generation[0]
            index = widget.get_active()
            if index < 0:
                return
            runner, record = records[index]
            output.get_buffer().set_text(t(self.preferences.language, "progress_preparing"))
            def worker():
                try:
                    message = record.preview(runner) or t(self.preferences.language, "rollback_no_changes")
                except Exception as exc:
                    message = str(exc)
                def finish():
                    if token == generation[0]:
                        output.get_buffer().set_text(message)
                    return False
                GLib.idle_add(finish)
            threading.Thread(target=worker, daemon=True).start()
        combo.connect("changed", changed)
        if records:
            combo.set_active(len(records) - 1)
        else:
            output.get_buffer().set_text(t(self.preferences.language, "rollback_no_record"))
        dialog.show_all()
        dialog.run()
        generation[0] += 1
        dialog.destroy()

    def _register_active_op(
        self,
        key: str,
        command: str,
        summary: str,
        pixbuf: GdkPixbuf.Pixbuf | None,
        download_size: str = "",
        cancel_fn=None,
        runner=None,
        op_id=None,
    ) -> None:
        self._active_ops[key] = {
            "command": command,
            "base_summary": summary,
            "display_summary": summary,
            "pixbuf": pixbuf,
            "cancel_fn": cancel_fn,
            "runner": runner,
            "op_id": op_id,
        }
        if runner is not None and op_id:
            runner.prepare_operation(op_id)
        if not getattr(self, "_operation_poll_source", None):
            self._operation_poll_source = GLib.timeout_add(250, self._poll_operation_rows)
        self._refresh_operations_list()

    def _operation_capabilities(self, op):
        runner, op_id = op.get("runner"), op.get("op_id")
        if runner is None or not op_id:
            return {}
        return runner.operation_status(op_id)

    def _poll_operation_rows(self):
        if not self._active_ops or getattr(self, "_release_check_destroyed", False):
            self._operation_poll_source = None
            return False
        for row in self.operations_store:
            op = self._active_ops.get(row[4])
            if op:
                capabilities = self._operation_capabilities(op)
                state = t(self.preferences.language, "operation_state_" + capabilities.get("state", "UNKNOWN").lower())
                text = f"{op['display_summary']} — {state}"
                if row[_OC_COMMAND] != text:
                    row[_OC_COMMAND] = text
        self._sync_cancel_capabilities()
        return True

    def _sync_cancel_capabilities(self):
        capabilities = [self._operation_capabilities(op) for op in self._active_ops.values()]
        self.operations_cancel_btn.set_visible(any(c.get("can_cancel") or c.get("can_request_cancel") for c in capabilities))
        self._on_operations_selection_changed(self.operations_tree.get_selection())

    def _request_operation_cancel(self, key):
        op = self._active_ops.get(key)
        if not op or op.get("runner") is None:
            return False
        result = op["runner"].request_cancel(op["op_id"])
        if result != "finished":
            self.clear_cached_sudo_password()
        if result == "pending":
            op["display_summary"] = t(self.preferences.language, "cancel_pending")
        self._poll_operation_rows()
        return result == "cancelled"

    def _unregister_active_op(self, key: str, success=None, message="") -> None:
        operation = self._active_ops.pop(key, None)
        if operation and operation.get("runner") is not None:
            operation["runner"].complete_task(operation["op_id"], bool(success))
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
            # The bounded timer updates only changed rows and keeps selection.

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
        model, selected = self.operations_tree.get_selection().get_selected()
        selected_key = model[selected][4] if selected is not None else None
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
        if selected_key:
            for row in self.operations_store:
                if row[4] == selected_key:
                    self.operations_tree.get_selection().select_iter(row.iter)
                    break
        self._sync_cancel_capabilities()

    def _on_operations_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        key = model.get_value(it, 4) if it is not None else ""
        operation = self._active_ops.get(key, {})
        capabilities = self._operation_capabilities(operation)
        self.operations_pause_btn.set_sensitive(False)
        self.operations_cancel_btn.set_sensitive(bool(capabilities.get("can_cancel") or capabilities.get("can_request_cancel")))
        label = "request_cancel" if capabilities.get("can_request_cancel") else "btn_cancel"
        self.operations_cancel_btn.set_label(t(self.preferences.language, label))
        self.operations_cancel_btn.set_tooltip_text(t(self.preferences.language, "cancel_pending" if capabilities.get("critical") else "btn_cancel"))

    def _on_operations_pause(self, *_args) -> None:
        return

    def _on_operations_cancel(self, *_args) -> None:
        sel = self.operations_tree.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        key = model.get_value(it, 4)
        self._request_operation_cancel(key)

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
