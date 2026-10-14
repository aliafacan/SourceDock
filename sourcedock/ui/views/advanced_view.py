"""Read-only source inspection and explicit application-list restoration."""

import json
from pathlib import Path
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk, Pango

from sourcedock.backend.sources import list_sources
from sourcedock.core.app_lists import install_restore_item, plan_restore
from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.i18n import t
from sourcedock.ui.components.common import ContentState


class AdvancedViewMixin:
    def on_open_sources(self, _button):
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "settings_sources"), transient_for=self, modal=True, destroy_with_parent=True
        )
        dialog.set_default_size(760, 440)
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda widget, _response: widget.destroy())
        dialog._closed = False
        dialog.connect("destroy", lambda widget: setattr(widget, "_closed", True))
        model = Gtk.ListStore(str, str, str, str)
        tree = Gtk.TreeView(model=model)
        for index, key in enumerate(
            ("applications_col_source", "sources_name", "sources_detail", "sources_channel")
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
            column = Gtk.TreeViewColumn(t(lang, key), renderer, text=index)
            column.set_resizable(True)
            column.set_expand(index == 2)
            tree.append_column(column)
        scroller = Gtk.ScrolledWindow()
        scroller.add(tree)
        state = ContentState(scroller)
        state.show_state(t(lang, "sources_loading"), loading=True)
        dialog.get_content_area().pack_start(state, True, True, 0)
        dialog.show_all()

        def finish(rows, error):
            if dialog._closed:
                return False
            for row in rows:
                model.append(row)
            if error:
                state.show_state(t(lang, "sources_error"), error, error=True)
            elif rows:
                state.show_content()
            else:
                state.show_state(t(lang, "sources_empty"))
            return False

        def worker():
            try:
                rows = list_sources(
                    self.application_registry.runner, self.application_registry.native_provider.source
                )
                GLib.idle_add(finish, rows, None)
            except Exception as exc:
                GLib.idle_add(finish, [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_import_application_list(self, _button):
        lang = self.preferences.language
        chooser = Gtk.FileChooserDialog(
            title=t(lang, "restore_title"), transient_for=self, action=Gtk.FileChooserAction.OPEN
        )
        chooser.add_buttons(
            t(lang, "password_cancel"), Gtk.ResponseType.CANCEL, t(lang, "dialog_open"), Gtk.ResponseType.OK
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("JSON")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)
        response = chooser.run()
        filename = chooser.get_filename()
        chooser.destroy()
        if response != Gtk.ResponseType.OK or not filename:
            return
        try:
            path = Path(filename)
            if path.stat().st_size > 1024 * 1024:
                raise BackendError("Application list exceeds the size limit.")
            data = json.loads(path.read_text(encoding="utf-8"))
            items = plan_restore(data, self.application_registry.distro, self.applications)
            self._show_restore_preview(items)
        except (OSError, ValueError, BackendError) as exc:
            self._show_error_dialog(str(exc))

    def _show_restore_preview(self, items):
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "restore_title"), transient_for=self, modal=True, destroy_with_parent=True
        )
        dialog.set_default_size(780, 480)
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        apply = dialog.add_button(t(lang, "restore_apply"), Gtk.ResponseType.OK)
        apply.set_sensitive(False)
        description = Gtk.Label(label=t(lang, "restore_versions_info"), xalign=0)
        description.set_line_wrap(True)
        description.set_margin_bottom(12)
        dialog.get_content_area().pack_start(description, False, False, 0)
        model = Gtk.ListStore(bool, str, str, str, str, GObject.TYPE_PYOBJECT)
        for item in items:
            model.append(
                [
                    False,
                    item.name,
                    item.source.upper(),
                    item.version,
                    t(lang, item.reason) if item.reason else t(lang, "restore_ready"),
                    item,
                ]
            )
        tree = Gtk.TreeView(model=model)
        toggle = Gtk.CellRendererToggle()

        def toggled(_cell, path):
            iterator = model.get_iter(path)
            if model.get_value(iterator, 5).eligible:
                model.set_value(iterator, 0, not model.get_value(iterator, 0))
            apply.set_sensitive(any(row[0] for row in model))

        toggle.connect("toggled", toggled)
        tree.append_column(Gtk.TreeViewColumn("", toggle, active=0))
        for index, key in (
            (1, "applications_col_app"),
            (2, "applications_col_source"),
            (3, "restore_recorded_version"),
            (4, "operation_result"),
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(t(lang, key), renderer, text=index)
            column.set_expand(index == 1)
            tree.append_column(column)
        scroller = Gtk.ScrolledWindow()
        scroller.add(tree)
        dialog.get_content_area().pack_start(scroller, True, True, 0)
        dialog.show_all()
        response = dialog.run()
        selected = [row[5] for row in model if row[0] and row[5].eligible]
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not selected:
            return
        completed = set()

        def worker():
            failures = []
            for item in selected:
                identity = (item.source, item.package)
                if identity in completed:
                    continue
                try:
                    install_restore_item(self.application_registry, item)
                    completed.add(identity)
                except AuthRequiredError:
                    raise
                except BackendError as exc:
                    failures.append(f"{item.name}: {exc}")
            if failures:
                GLib.idle_add(self.reload_applications_async)
                raise BackendError("\n".join(failures))

        self._run_application_task(
            "restore",
            worker,
            "store_install_done",
            "restore_title",
            True,
            t(lang, "restore_count", count=len(selected)),
        )
