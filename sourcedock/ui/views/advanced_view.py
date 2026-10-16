"""Read-only source inspection and explicit application-list restoration."""

import json
from pathlib import Path
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from sourcedock.backend.sources import add_flatpak_remote, list_sources, remove_flatpak_remote
from sourcedock.core.app_lists import install_restore_item, plan_restore
from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.i18n import t
from sourcedock.ui.components.common import ContentState, make_window_movable, prepare_dialog, style_tree_view


class AdvancedViewMixin:
    def on_open_sources(self, _button):
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "settings_sources"), transient_for=self, modal=True, destroy_with_parent=True
        )
        prepare_dialog(dialog, width=860, height=460)
        dialog.add_button(t(lang, "sources_add_remote"), Gtk.ResponseType.APPLY)
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

        def on_dialog_response(widget, response):
            if response == Gtk.ResponseType.APPLY:
                self._show_add_remote_dialog(dialog, on_success=reload_sources)
            else:
                widget.destroy()

        dialog.connect("response", on_dialog_response)
        dialog._closed = False
        dialog.connect("destroy", lambda widget: setattr(widget, "_closed", True))
        model = Gtk.ListStore(str, str, str, str)
        tree = Gtk.TreeView(model=model)
        style_tree_view(tree)
        tree.set_has_tooltip(True)
        for index, key in enumerate(
            ("applications_col_source", "sources_name", "sources_detail", "sources_channel")
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
            column = Gtk.TreeViewColumn(t(lang, key), renderer, text=index)
            column.set_resizable(True)
            column.set_expand(index == 2)
            column.set_min_width((100, 170, 360, 220)[index])
            tree.append_column(column)

        def query_tooltip(treeview, x, y, _keyboard_mode, tooltip):
            hit = treeview.get_path_at_pos(int(x), int(y))
            if not hit:
                return False
            path, column, _cell_x, _cell_y = hit
            iterator = model.get_iter(path)
            if iterator is None:
                return False
            try:
                column_index = treeview.get_columns().index(column)
            except ValueError:
                return False
            value = model.get_value(iterator, column_index)
            if value:
                tooltip.set_text(value)
                treeview.set_tooltip_cell(tooltip, path, column, None)
                return True
            return False

        def copy_address(_tree, event):
            if event.state & Gdk.ModifierType.CONTROL_MASK and Gdk.keyval_name(event.keyval) in ("c", "C"):
                selected = tree.get_selection().get_selected()
                if selected[1] is not None:
                    value = model.get_value(selected[1], 2)
                    Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value or "", -1)
                    return True
            return False

        def copy_context(_tree, event):
            if event.button != 3:
                return False
            hit = tree.get_path_at_pos(int(event.x), int(event.y))
            if not hit:
                return False
            path, _column, _cell_x, _cell_y = hit
            tree.get_selection().select_path(path)
            iterator = model.get_iter(path)
            if iterator is None:
                return False
            source_type = model.get_value(iterator, 0) or ""
            remote_name = model.get_value(iterator, 1) or ""
            address = model.get_value(iterator, 2) or ""
            menu = Gtk.Menu()
            copy_item = Gtk.MenuItem(label=t(lang, "sources_copy_address"))
            copy_item.set_sensitive(bool(address and address != t(lang, "sources_empty_value")))
            copy_item.connect(
                "activate",
                lambda _item: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(address, -1),
            )
            menu.append(copy_item)

            if source_type == "Flatpak" and remote_name and remote_name != t(lang, "sources_empty_value"):
                menu.append(Gtk.SeparatorMenuItem())
                remove_item = Gtk.MenuItem(label=t(lang, "sources_remove_remote"))

                def on_remove_activate(_item):
                    confirm = Gtk.MessageDialog(
                        transient_for=dialog,
                        modal=True,
                        message_type=Gtk.MessageType.WARNING,
                        buttons=Gtk.ButtonsType.OK_CANCEL,
                        text=t(lang, "sources_remove_confirm", name=remote_name),
                    )
                    resp = confirm.run()
                    confirm.destroy()
                    if resp == Gtk.ResponseType.OK:
                        def remove_worker():
                            ok, _err = remove_flatpak_remote(
                                self.application_registry.runner, remote_name, user=True
                            )
                            GLib.idle_add(reload_sources)
                            if ok and hasattr(self, "show_toast"):
                                GLib.idle_add(self.show_toast, t(lang, "sources_remote_removed"), "info")
                        threading.Thread(target=remove_worker, daemon=True).start()

                remove_item.connect("activate", on_remove_activate)
                menu.append(remove_item)

            menu.show_all()
            menu.popup_at_pointer(event)
            return True

        tree.connect("query-tooltip", query_tooltip)
        tree.connect("key-press-event", copy_address)
        tree.connect("button-press-event", copy_context)
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
                model.append([value or t(lang, "sources_empty_value") for value in row])
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

        def reload_sources():
            model.clear()
            state.show_state(t(lang, "sources_loading"), loading=True)
            threading.Thread(target=worker, daemon=True).start()

        threading.Thread(target=worker, daemon=True).start()

    def _show_add_remote_dialog(self, parent_dialog, on_success):
        lang = self.preferences.language
        add_diag = Gtk.Dialog(
            title=t(lang, "sources_add_remote_title"),
            transient_for=parent_dialog,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(add_diag, width=520, height=220)
        add_diag.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        add_btn = add_diag.add_button(t(lang, "sources_add_remote"), Gtk.ResponseType.OK)
        add_btn.get_style_context().add_class("suggested-action")

        box = add_diag.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        box.pack_start(grid, False, False, 0)

        name_lbl = Gtk.Label(label=t(lang, "sources_remote_name"), xalign=0)
        name_entry = Gtk.Entry()
        name_entry.set_hexpand(True)
        name_entry.set_placeholder_text("flathub")

        url_lbl = Gtk.Label(label=t(lang, "sources_remote_url"), xalign=0)
        url_entry = Gtk.Entry()
        url_entry.set_hexpand(True)
        url_entry.set_placeholder_text("https://dl.flathub.org/repo/flathub.flatpakrepo")

        err_lbl = Gtk.Label(xalign=0)
        err_lbl.get_style_context().add_class("error-text")

        grid.attach(name_lbl, 0, 0, 1, 1)
        grid.attach(name_entry, 1, 0, 1, 1)
        grid.attach(url_lbl, 0, 1, 1, 1)
        grid.attach(url_entry, 1, 1, 1, 1)
        box.pack_start(err_lbl, False, False, 0)

        add_diag.show_all()
        while True:
            resp = add_diag.run()
            if resp != Gtk.ResponseType.OK:
                add_diag.destroy()
                return
            remote_name = name_entry.get_text().strip()
            remote_url = url_entry.get_text().strip()
            from sourcedock.backend.sources import add_flatpak_remote, validate_remote_name, validate_remote_url
            if not validate_remote_name(remote_name) or not validate_remote_url(remote_url):
                err_lbl.set_text(t(lang, "sources_invalid_input"))
                continue
            add_diag.destroy()

            def add_worker():
                ok, err = add_flatpak_remote(
                    self.application_registry.runner, remote_name, remote_url, user=True
                )
                if ok:
                    GLib.idle_add(on_success)
                    if hasattr(self, "show_toast"):
                        GLib.idle_add(self.show_toast, t(lang, "sources_remote_added"), "success")
                elif hasattr(self, "show_toast"):
                    GLib.idle_add(self.show_toast, err or t(lang, "sources_error"), "error")

            threading.Thread(target=add_worker, daemon=True).start()
            break


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
        make_window_movable(dialog)
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
