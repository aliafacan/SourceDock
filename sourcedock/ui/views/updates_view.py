"""Unified updates with explicit selection and firmware confirmation."""

from pathlib import Path
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, GObject, Gtk, Pango

from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.i18n import t
from sourcedock.ui.components.common import ContentState, icon_button, set_status, style_tree_view


class UpdatesViewMixin:
    def _build_updates_page(self, container):
        self.update_items = []
        self.updates_loading = False
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.updates_page_title = Gtk.Label(xalign=0)
        self.updates_page_title.get_style_context().add_class("page-title")
        intro.pack_start(self.updates_page_title, False, False, 0)
        self.updates_page_subtitle = Gtk.Label(xalign=0)
        self.updates_page_subtitle.set_line_wrap(True)
        self.updates_page_subtitle.get_style_context().add_class("dim-label")
        intro.pack_start(self.updates_page_subtitle, False, False, 0)
        container.pack_start(intro, False, False, 0)

        self.updates_summary_cards = Gtk.Box(spacing=8)
        self.updates_summary_cards.set_homogeneous(True)
        self.updates_stat_labels = {}
        for group, icon, title_key in (
            ("applications", "application-x-executable-symbolic", "updates_stat_applications"),
            ("system", "package-x-generic-symbolic", "updates_stat_system"),
            ("runtimes", "application-x-addon-symbolic", "updates_stat_runtimes"),
            ("firmware", "computer-symbolic", "updates_stat_firmware"),
        ):
            frame = Gtk.Frame()
            frame.get_style_context().add_class("summary-card")
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.set_margin_top(10)
            card.set_margin_bottom(10)
            card.set_margin_start(12)
            card.set_margin_end(12)
            top = Gtk.Box(spacing=8)
            top.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            title = Gtk.Label(xalign=0)
            title.get_style_context().add_class("dim-label")
            top.pack_start(title, True, True, 0)
            card.pack_start(top, False, False, 0)
            count = Gtk.Label(label="0", xalign=0)
            count.get_style_context().add_class("summary-count")
            card.pack_start(count, False, False, 0)
            frame.add(card)
            self.updates_summary_cards.pack_start(frame, True, True, 0)
            self.updates_stat_labels[group] = (title, count, title_key)
        container.pack_start(self.updates_summary_cards, False, False, 0)

        toolbar = Gtk.Box(spacing=8)
        self.updates_summary = Gtk.Label(xalign=0)
        toolbar.pack_start(self.updates_summary, True, True, 0)
        self.updates_refresh_btn = Gtk.Button()
        self.updates_refresh_btn.connect("clicked", lambda _button: self._reload_updates_async())
        toolbar.pack_end(self.updates_refresh_btn, False, False, 0)
        container.pack_start(toolbar, False, False, 0)
        self.updates_reboot_banner = Gtk.Label(xalign=0)
        self.updates_reboot_banner.set_line_wrap(True)
        self.updates_reboot_banner.get_style_context().add_class("warning-text")
        self.updates_reboot_banner.set_no_show_all(True)
        container.pack_start(self.updates_reboot_banner, False, False, 0)
        self.updates_model = Gtk.TreeStore(
            bool, str, str, str, str, GObject.TYPE_PYOBJECT, GdkPixbuf.Pixbuf
        )
        self.updates_tree = Gtk.TreeView(model=self.updates_model)
        style_tree_view(self.updates_tree)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_update_toggled)
        column = Gtk.TreeViewColumn("", toggle, active=0)
        column.set_cell_data_func(
            toggle,
            lambda _column, cell, model, iterator, _data: cell.set_property(
                "visible", model.get_value(iterator, 5) is not None
            ),
        )
        self.updates_tree.append_column(column)
        self.updates_columns = []
        for index, key in (
            (1, "applications_col_app"),
            (2, "applications_col_source"),
            (3, "packages_col_version"),
            (4, "packages_col_new_version"),
        ):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            if index != 1:
                renderer.set_property("xalign", 0.0)
            if index == 1:
                column = Gtk.TreeViewColumn(t(self.preferences.language, key))
                icon_renderer = Gtk.CellRendererPixbuf()
                icon_renderer.set_property("xpad", 4)
                column.pack_start(icon_renderer, False)
                column.add_attribute(icon_renderer, "pixbuf", 6)
                column.set_cell_data_func(
                    icon_renderer,
                    lambda _column, cell, model, iterator, _data: cell.set_property(
                        "visible", model.get_value(iterator, 5) is not None
                    ),
                )
                column.pack_start(renderer, True)
                column.add_attribute(renderer, "text", index)
            else:
                column = Gtk.TreeViewColumn(t(self.preferences.language, key), renderer, text=index)
            column.set_expand(index == 1)
            column.set_resizable(True)
            self.updates_tree.append_column(column)
            self.updates_columns.append((column, key))
            if index == 1:
                column.set_cell_data_func(renderer, self._update_name_cell_data)
            else:
                column.set_cell_data_func(renderer, self._update_detail_cell_data)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.updates_tree)
        self.updates_state = ContentState(scroller)
        container.pack_start(self.updates_state, True, True, 0)
        self.updates_status = Gtk.Label(xalign=0)
        self.updates_status.set_line_wrap(True)
        container.pack_start(self.updates_status, False, False, 0)
        bar = Gtk.Box(spacing=8)
        self.updates_select_all_btn = Gtk.CheckButton()
        self.updates_select_all_btn.connect("toggled", self._on_updates_select_all)
        bar.pack_start(self.updates_select_all_btn, False, False, 0)
        self.updates_selection_summary = Gtk.Label(xalign=0)
        self.updates_selection_summary.get_style_context().add_class("dim-label")
        bar.pack_start(self.updates_selection_summary, True, True, 0)
        self.updates_apply_btn = Gtk.Button()
        self.updates_apply_btn.get_style_context().add_class("suggested-action")
        self.updates_apply_btn.connect("clicked", self._on_apply_updates)
        self.updates_apply_btn.set_sensitive(False)
        bar.pack_end(self.updates_apply_btn, False, False, 0)
        container.pack_start(bar, False, False, 0)
        self._refresh_updates_texts()

    def _refresh_updates_texts(self):
        lang = self.preferences.language
        self.updates_page_title.set_text(t(lang, "updates_page_title"))
        self.updates_page_subtitle.set_text(t(lang, "updates_page_subtitle"))
        icon_button(self.updates_refresh_btn, "view-refresh-symbolic", t(lang, "updates_check"))
        self.updates_select_all_btn.set_label(t(lang, "updates_select_all"))
        self.updates_apply_btn.set_label(t(lang, "updates_apply"))
        self.updates_summary.set_text(t(lang, "updates_count", count=len(self.update_items)))
        for title, _count, title_key in self.updates_stat_labels.values():
            title.set_text(t(lang, title_key))
        for column, key in self.updates_columns:
            column.set_title(t(lang, key))
        self._refresh_selection_summary()

    def _update_name_cell_data(self, _column, cell, model, iterator, _data):
        is_group = model.get_value(iterator, 5) is None
        cell.set_property("weight", 700 if is_group else 400)
        cell.set_property("foreground-set", True)
        cell.set_property("foreground", "#f3ce45" if is_group else "#f0f2f3")

    def _update_detail_cell_data(self, _column, cell, model, iterator, _data):
        cell.set_property("visible", model.get_value(iterator, 5) is not None)

    def _refresh_selection_summary(self):
        if not hasattr(self, "updates_selection_summary"):
            return
        selected = len(self._selected_updates()) if hasattr(self, "updates_model") else 0
        self.updates_selection_summary.set_text(
            t(self.preferences.language, "updates_selected_count", count=selected)
        )

    def _reload_updates_async(self):
        if self.updates_loading or self.applications_busy:
            return
        self.updates_loading = True
        self.updates_refresh_btn.set_sensitive(False)
        self.updates_state.show_state(t(self.preferences.language, "updates_loading"), loading=True)

        def worker():
            try:
                snapshot = self.application_registry.load()
                packages = self.application_registry.list_packages()
                items = build_update_catalog(
                    snapshot.applications, packages, self.application_registry.native_provider.source
                )
                GLib.idle_add(self._finish_updates_load, items, snapshot.provider_errors, None)
            except Exception as exc:
                GLib.idle_add(self._finish_updates_load, [], [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_updates_load(self, items, provider_errors, error):
        self.updates_loading = False
        self.updates_refresh_btn.set_sensitive(True)
        self.update_items = items
        self.updates_model.clear()
        lang = self.preferences.language
        groups = {}
        for item in items:
            if item.group not in groups:
                group_count = sum(candidate.group == item.group for candidate in items)
                groups[item.group] = self.updates_model.append(
                    None,
                    [
                        False,
                        f"{t(lang, f'updates_group_{item.group}')}  ·  {group_count}",
                        "",
                        "",
                        "",
                        None,
                        None,
                    ],
                )
            app = item.application
            self.updates_model.append(
                groups[item.group],
                [
                    False,
                    app.name,
                    app.source.upper(),
                    app.version or "-",
                    item.new_version or "-",
                    item,
                    self._get_update_pixbuf(app),
                ],
            )
        self.updates_tree.expand_all()
        self.updates_apply_btn.set_sensitive(False)
        self.updates_select_all_btn.set_active(False)
        for group, (_title, count_label, _title_key) in self.updates_stat_labels.items():
            count_label.set_text(str(sum(item.group == group for item in items)))
        if error:
            self.updates_state.show_state(t(lang, "updates_error"), error, error=True)
        elif items:
            self.updates_state.show_content()
        else:
            self.updates_state.show_state(t(lang, "updates_empty"), t(lang, "updates_empty_body"))
        message = "\n".join(provider_errors)
        reboot_required = Path("/var/run/reboot-required").exists()
        self.updates_reboot_banner.set_text(t(lang, "updates_reboot_required") if reboot_required else "")
        self.updates_reboot_banner.set_visible(reboot_required)
        if reboot_required:
            message = t(lang, "updates_reboot_required") + ("\n" + message if message else "")
        set_status(self.updates_status, message, bool(error or provider_errors))
        self._refresh_updates_texts()
        self._refresh_update_count()
        return False

    def _get_update_pixbuf(self, application):
        getter = getattr(self, "_get_app_pixbuf", None)
        if getter is None:
            return None
        try:
            return getter(application)
        except Exception:
            return None

    def _on_update_toggled(self, _cell, path):
        iterator = self.updates_model.get_iter(path)
        item = self.updates_model.get_value(iterator, 5)
        if item is not None and item.application.update_supported:
            self.updates_model.set_value(iterator, 0, not self.updates_model.get_value(iterator, 0))
        self.updates_apply_btn.set_sensitive(bool(self._selected_updates()))
        self._refresh_selection_summary()

    def _selected_updates(self):
        selected = []
        self.updates_model.foreach(
            lambda model, _path, iterator, _data=None: (
                selected.append(model.get_value(iterator, 5))
                if model.get_value(iterator, 0) and model.get_value(iterator, 5) is not None
                else None
            )
        )
        return selected

    def _on_updates_select_all(self, button):
        active = button.get_active()

        def select(model, _path, iterator, _data=None):
            item = model.get_value(iterator, 5)
            if item is not None:
                model.set_value(iterator, 0, active and item.application.update_supported)

        self.updates_model.foreach(select)
        self.updates_apply_btn.set_sensitive(bool(self._selected_updates()))
        self._refresh_selection_summary()

    def _on_apply_updates(self, _button):
        items = self._selected_updates()
        if not items or self.applications_busy:
            return
        lang = self.preferences.language
        if any(item.group == "firmware" for item in items) and not self._confirm_firmware_update():
            return
        completed = set()

        def worker():
            failures = []
            for item in items:
                if item.application.id in completed:
                    continue
                try:
                    self.application_registry.update(item.application)
                    completed.add(item.application.id)
                except AuthRequiredError:
                    raise
                except BackendError as exc:
                    failures.append(f"{item.application.name}: {exc}")
            GLib.idle_add(self._reload_updates_async)
            if failures:
                raise BackendError("\n".join(failures))

        self._run_application_task(
            "updates",
            worker,
            "packages_update_done",
            "nav_updates",
            True,
            t(lang, "updates_count", count=len(items)),
        )

    def _confirm_firmware_update(self):
        lang = self.preferences.language
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=t(lang, "firmware_confirm_title"),
        )
        dialog.format_secondary_text(t(lang, "firmware_confirm_body"))
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK
