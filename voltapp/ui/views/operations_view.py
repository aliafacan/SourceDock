#!/usr/bin/env python3
"""Aktif süreçler ve paket işlemleri izleme görünümü."""

from __future__ import annotations

import os
import signal
import subprocess

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from voltapp.i18n import t

_OC_ICON = 0
_OC_PID = 1
_OC_COMMAND = 2
_OC_PACKAGES = 3


class OperationsViewMixin:
    """İşlemler (Operations) sekmesi kurulumu ve süreç yönetimi."""

    def _build_operations_page(self, container: Gtk.Box) -> None:
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.operations_title_label = Gtk.Label(label="Aktif Paket İşlemleri")
        self.operations_title_label.set_xalign(0)
        title_box.pack_start(self.operations_title_label, True, True, 0)

        self.operations_refresh_btn = Gtk.Button(label="Yenile")
        self.operations_refresh_btn.connect("clicked", self._on_operations_refresh)
        title_box.pack_start(self.operations_refresh_btn, False, False, 0)
        container.pack_start(title_box, False, False, 0)

        self.operations_subtitle_label = Gtk.Label(
            label="Sistemde veya VoltApp içinde çalışan paket yönetim süreçlerini izle ve yönet."
        )
        self.operations_subtitle_label.set_xalign(0)
        self.operations_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.operations_subtitle_label, False, False, 0)

        self.operations_store = Gtk.ListStore(
            GdkPixbuf.Pixbuf,
            str,
            str,
            str,
        )
        self.operations_tree = Gtk.TreeView(model=self.operations_store)
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
        self.operations_tree.append_column(self.operations_tree_col_pid)

        pkg_rend = Gtk.CellRendererText()
        pkg_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.operations_tree_col_target = Gtk.TreeViewColumn("Hedef Paketler", pkg_rend, text=_OC_PACKAGES)
        self.operations_tree_col_target.set_expand(True)
        self.operations_tree.append_column(self.operations_tree_col_target)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.operations_tree)
        container.pack_start(scroller, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.operations_pause_btn = Gtk.Button(label="Duraklat")
        self.operations_pause_btn.connect("clicked", self._on_operations_pause)
        self.operations_pause_btn.set_sensitive(False)
        action_bar.pack_start(self.operations_pause_btn, False, False, 0)

        self.operations_cancel_btn = Gtk.Button(label="Görevi İptal Et")
        self.operations_cancel_btn.get_style_context().add_class("destructive-action")
        self.operations_cancel_btn.connect("clicked", self._on_operations_cancel)
        self.operations_cancel_btn.set_sensitive(False)
        action_bar.pack_start(self.operations_cancel_btn, False, False, 0)

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

    def _unregister_active_op(self, key: str) -> None:
        self._active_ops.pop(key, None)
        self._refresh_operations_list()

    def _update_op_row(self, key: str, fraction: float, label: str) -> None:
        op = self._active_ops.get(key)
        if op:
            op["display_summary"] = f"{op['base_summary']} ({label})"

    def _on_operations_refresh(self, *_args) -> None:
        self._refresh_operations_list()

    def _refresh_operations_list(self) -> None:
        self.operations_store.clear()
        lang = self.preferences.language
        for key, op in self._active_ops.items():
            self.operations_store.append([
                op.get("pixbuf"),
                "VoltApp",
                op.get("display_summary", t(lang, "operations_in_progress")),
                op.get("command", ""),
            ])
        try:
            holders = self.application_registry.runner._apt_lock_holders()
            for pid, args in holders:
                self.operations_store.append([
                    None,
                    str(pid),
                    args,
                    "APT / DPKG",
                ])
        except Exception:
            pass

    def _on_operations_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        has_sel = it is not None
        self.operations_pause_btn.set_sensitive(has_sel)
        self.operations_cancel_btn.set_sensitive(has_sel)

    def _on_operations_pause(self, *_args) -> None:
        sel = self.operations_tree.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        pid_str = model.get_value(it, _OC_PID)
        if pid_str.isdigit():
            try:
                os.kill(int(pid_str), signal.SIGSTOP)
            except Exception as exc:
                self._show_error_dialog(f"PID {pid_str} duraklatılamadı: {exc}")

    def _on_operations_cancel(self, *_args) -> None:
        sel = self.operations_tree.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return
        pid_str = model.get_value(it, _OC_PID)
        if pid_str.isdigit():
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except Exception as exc:
                self._show_error_dialog(f"PID {pid_str} sonlandırılamadı: {exc}")
        self._refresh_operations_list()

