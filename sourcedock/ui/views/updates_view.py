"""Unified updates with explicit selection and firmware confirmation."""

from pathlib import Path
import threading

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango

from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.models import SOURCE_APT
from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.i18n import source_name, t, translate_provider_error, translate_provider_notice
from sourcedock.ui.components.dialogs import show_firmware_confirmation
from sourcedock.theme import PALETTES, resolve_theme
from sourcedock.ui.components.common import ContentState, icon_button, style_tree_view


class UpdatesViewMixin:
    def _build_updates_page(self, container):
        self.update_items = []
        self.updates_loading = False
        self._updates_status_messages = []
        self._updates_status_error = None
        self.updates_active_group = None
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
        self.updates_stat_buttons = {}
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
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_can_focus(True)
            button.get_style_context().add_class("flat")
            button.set_tooltip_text(t(self.preferences.language, title_key))
            button.add(frame)
            button.connect("clicked", self._on_update_group_card_clicked, group)
            self.updates_summary_cards.pack_start(button, True, True, 0)
            self.updates_stat_buttons[group] = button
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
        self.updates_tree.set_has_tooltip(True)
        self.updates_tree.connect("query-tooltip", self._on_updates_query_tooltip)
        self.updates_tree.connect("key-press-event", self._on_updates_key_press)
        self.updates_tree.connect("button-press-event", self._on_updates_button_press)
        self.updates_tree.connect("popup-menu", self._on_updates_popup_menu)
        toggle = Gtk.CellRendererToggle()
        toggle.set_property("radio", False)
        self.updates_toggle_renderer = toggle
        toggle.connect("toggled", self._on_update_toggled)
        column = Gtk.TreeViewColumn("", toggle, active=0)
        column.set_cell_data_func(
            toggle,
            self._update_toggle_cell_data,
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
                    self._update_icon_cell_data,
                )
                column.pack_start(renderer, True)
                column.add_attribute(renderer, "text", index)
            else:
                column = Gtk.TreeViewColumn(t(self.preferences.language, key), renderer, text=index)
            column.set_expand(index == 1)
            column.set_resizable(True)
            if index == 2:
                column.set_min_width(96)
                column.set_fixed_width(112)
            elif index == 3:
                column.set_min_width(128)
                column.set_fixed_width(145)
            elif index == 4:
                column.set_min_width(128)
                column.set_fixed_width(145)
            if index in (3, 4):
                header_label = Gtk.Label(label=t(self.preferences.language, key), xalign=0)
                header_label.set_ellipsize(Pango.EllipsizeMode.END)
                header_label.set_max_width_chars(12)
                header_label.set_tooltip_text(t(self.preferences.language, key))
                column.set_widget(header_label)
                header_label.show()
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
        self.updates_status_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.updates_status_panel.get_style_context().add_class("updates-status-panel")
        self.updates_status_panel.set_no_show_all(True)
        self.updates_status_panel.hide()
        status_row = Gtk.Box(spacing=8)
        self.updates_status_row = status_row
        self.updates_status_icon = Gtk.Image.new_from_icon_name(
            "dialog-information-symbolic", Gtk.IconSize.BUTTON
        )
        status_row.pack_start(self.updates_status_icon, False, False, 0)
        self.updates_status = Gtk.Label(xalign=0)
        self.updates_status.set_ellipsize(Pango.EllipsizeMode.END)
        self.updates_status.set_max_width_chars(140)
        status_row.pack_start(self.updates_status, True, True, 0)
        self.updates_status_details_btn = Gtk.Button()
        self.updates_status_details_btn.connect("clicked", self._on_updates_status_details_clicked)
        status_row.pack_end(self.updates_status_details_btn, False, False, 0)
        self.updates_status_panel.pack_start(status_row, False, False, 0)
        self.updates_status_details = Gtk.Label(xalign=0)
        self.updates_status_details.set_line_wrap(True)
        self.updates_status_details.set_selectable(True)
        self.updates_status_details.get_style_context().add_class("dim-label")
        self.updates_status_details.set_margin_start(28)
        self.updates_status_panel.pack_start(self.updates_status_details, False, False, 0)
        self.updates_status_details.hide()
        container.pack_start(self.updates_status_panel, False, False, 0)
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
        self._set_updates_status_details_button()
        visible_count = sum(
            item.group == self.updates_active_group
            for item in self.update_items
        ) if self.updates_active_group else len(self.update_items)
        self.updates_summary.set_text(t(lang, "updates_count", count=visible_count))
        for title, _count, title_key in self.updates_stat_labels.values():
            title.set_text(t(lang, title_key))
        for group, button in self.updates_stat_buttons.items():
            button.set_tooltip_text(t(lang, self.updates_stat_labels[group][2]))
            button.get_style_context().remove_class("summary-card-active")
            if self.updates_active_group == group:
                button.get_style_context().add_class("summary-card-active")
        for column, key in self.updates_columns:
            column.set_title(t(lang, key))
            if column.get_widget() is not None:
                column.get_widget().set_text(t(lang, key))
                column.get_widget().set_tooltip_text(t(lang, key))
        self._refresh_selection_summary()
        if self._updates_status_messages or self._updates_status_error:
            expanded = self.updates_status_details.get_visible()
            self._render_updates_status(self._updates_status_messages, self._updates_status_error)
            self.updates_status_details.set_visible(expanded)
            self._set_updates_status_details_button()

    def _on_update_group_card_clicked(self, _button, group):
        """Filter the list to a summary category; clicking it again clears it."""
        self.updates_active_group = None if self.updates_active_group == group else group
        self._render_updates_model()
        self._refresh_updates_texts()

    def _render_updates_model(self):
        """Render only the active category while keeping summary totals intact."""
        self.updates_model.clear()
        visible_items = [
            item for item in self.update_items
            if self.updates_active_group is None or item.group == self.updates_active_group
        ]
        lang = self.preferences.language
        groups = {}
        for item in visible_items:
            if item.group not in groups:
                group_count = sum(candidate.group == item.group for candidate in visible_items)
                groups[item.group] = self.updates_model.append(
                    None,
                    [False, f"{t(lang, f'updates_group_{item.group}')}  ·  {group_count}", "", "", "", None, None],
                )
            app = item.application
            self.updates_model.append(
                groups[item.group],
                [
                    False, app.name, source_name(lang, app.source), app.version or "-",
                    item.new_version or t(lang, "version_no_update"), item, self._get_update_pixbuf(app),
                ],
            )
        self.updates_tree.expand_all()
        self.updates_apply_btn.set_sensitive(False)
        self.updates_select_all_btn.set_active(False)
        self._refresh_selection_summary()

    def _update_name_cell_data(self, _column, cell, model, iterator, _data):
        is_group = model.get_value(iterator, 5) is None
        cell.set_property("weight", 700 if is_group else 400)
        if is_group:
            palette = PALETTES[resolve_theme(self.preferences.theme)]
            cell.set_property("foreground-set", True)
            cell.set_property("foreground", palette["warning"])
            cell.set_property("background-set", True)
            cell.set_property("background", palette["surface"])
        else:
            cell.set_property("foreground-set", False)
            cell.set_property("background-set", False)

    def _update_toggle_cell_data(self, _column, cell, model, iterator, _data):
        item = model.get_value(iterator, 5)
        if item is not None:
            cell.set_property("visible", True)
            cell.set_property("activatable", bool(item.application.update_supported))
            cell.set_property("inconsistent", False)
            return
        children = model.iter_children(iterator)
        states = []
        while children is not None:
            child_item = model.get_value(children, 5)
            if child_item is not None and child_item.application.update_supported:
                states.append(bool(model.get_value(children, 0)))
            children = model.iter_next(children)
        cell.set_property("visible", True)
        cell.set_property("activatable", bool(states))
        cell.set_property("active", bool(states) and all(states))
        cell.set_property("inconsistent", bool(states) and not all(states))

    def _update_detail_cell_data(self, _column, cell, model, iterator, _data):
        is_group = model.get_value(iterator, 5) is None
        cell.set_property("visible", True)
        if is_group:
            palette = PALETTES[resolve_theme(self.preferences.theme)]
            cell.set_property("foreground-set", True)
            cell.set_property("foreground", palette["muted"])
            cell.set_property("background-set", True)
            cell.set_property("background", palette["surface"])
        else:
            cell.set_property("foreground-set", False)
            cell.set_property("background-set", False)

    def _update_icon_cell_data(self, _column, cell, model, iterator, _data):
        is_group = model.get_value(iterator, 5) is None
        cell.set_property("visible", not is_group)

    def _on_updates_query_tooltip(self, treeview, x, y, _keyboard_mode, tooltip):
        hit = treeview.get_path_at_pos(int(x), int(y))
        if not hit:
            return False
        path, column, _cell_x, _cell_y = hit
        if not self.updates_columns or column is not self.updates_columns[-1][0]:
            return False
        iterator = self.updates_model.get_iter(path)
        if iterator is None:
            return False
        item = self.updates_model.get_value(iterator, 5)
        if item is None or not item.new_version:
            tooltip.set_text(t(self.preferences.language, "updates_version_unavailable"))
            treeview.set_tooltip_cell(tooltip, path, column, None)
            return True
        return False

    def _refresh_selection_summary(self):
        if not hasattr(self, "updates_selection_summary"):
            return
        selected = len(self._selected_updates()) if hasattr(self, "updates_model") else 0
        self.updates_selection_summary.set_text(
            t(self.preferences.language, "updates_selected_count", count=selected)
        )
        selectable = sum(
            item.application.update_supported
            and (self.updates_active_group is None or item.group == self.updates_active_group)
            for item in self.update_items
        )
        self._syncing_updates_selection = True
        try:
            self.updates_select_all_btn.set_active(bool(selectable and selected == selectable))
            self.updates_select_all_btn.set_inconsistent(0 < selected < selectable)
            self.updates_select_all_btn.set_sensitive(bool(selectable))
        finally:
            self._syncing_updates_selection = False

    def _set_updates_status_details_button(self):
        if not hasattr(self, "updates_status_details_btn"):
            return
        expanded = self.updates_status_details.get_visible()
        icon_button(
            self.updates_status_details_btn,
            "go-up-symbolic" if expanded else "view-more-symbolic",
            t(
                self.preferences.language,
                "updates_status_details_hide" if expanded else "updates_status_details_show",
            ),
        )
        self.updates_status_details_btn.set_visible(bool(self.updates_status_details.get_text()))

    def _on_updates_status_details_clicked(self, _button):
        self.updates_status_details.set_visible(not self.updates_status_details.get_visible())
        self._set_updates_status_details_button()

    def _format_updates_status(self, provider_errors, error=None):
        """Keep the page compact while retaining full provider diagnostics."""
        messages = ([error] if error else []) + list(provider_errors or [])
        if not messages:
            return "", "", False

        summaries = []
        details = []
        provider_issue_count = 0
        for message in dict.fromkeys(messages):
            notice = translate_provider_notice(self.preferences.language, message, compact=True)
            if notice != message:
                summaries.append(notice)
            else:
                provider_issue_count += 1
            details.append(translate_provider_error(
                self.preferences.language, translate_provider_notice(self.preferences.language, message),
            ))

        if provider_issue_count:
            summary = t(
                self.preferences.language,
                "updates_status_source_warning" if provider_issue_count == 1 else "updates_status_source_warnings",
                count=provider_issue_count,
            )
            return summary, "\n".join(details), True

        return " · ".join(summaries), "\n".join(details), False

    def _render_updates_status(self, provider_errors, error=None):
        self._updates_status_messages = list(provider_errors or [])
        self._updates_status_error = error
        summary, details, is_error = self._format_updates_status(provider_errors, error)
        self.updates_status_details.set_text(details)
        self.updates_status_details.hide()
        self.updates_status_panel.get_style_context().remove_class("updates-status-error")
        self.updates_status_panel.get_style_context().remove_class("updates-status-notice")
        if not summary:
            self.updates_status_panel.hide()
            self._set_updates_status_details_button()
            return
        self.updates_status.set_text(summary)
        self.updates_status_row.show_all()
        self.updates_status_panel.get_style_context().add_class(
            "updates-status-error" if is_error else "updates-status-notice"
        )
        self.updates_status_icon.set_from_icon_name(
            "dialog-warning-symbolic" if is_error else "dialog-information-symbolic",
            Gtk.IconSize.BUTTON,
        )
        self.updates_status_panel.show()
        self.updates_status_details.hide()
        self._set_updates_status_details_button()

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
                GLib.idle_add(
                    self._finish_updates_load, items,
                    snapshot.provider_errors + snapshot.provider_notices, None,
                )
            except Exception as exc:
                GLib.idle_add(self._finish_updates_load, [], [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_updates_load(self, items, provider_errors, error):
        self.updates_loading = False
        self.updates_refresh_btn.set_sensitive(True)
        self.update_items = items
        lang = self.preferences.language
        self._render_updates_model()
        for group, (_title, count_label, _title_key) in self.updates_stat_labels.items():
            count_label.set_text(str(sum(item.group == group for item in items)))
        if error:
            self.updates_state.show_state(
                t(lang, "updates_error"),
                error,
                error=True,
                retry_callback=self._reload_updates_async,
                retry_label=t(lang, "retry_action"),
            )
        elif items:
            self.updates_state.show_content()
            if getattr(self.preferences, "notifications_enabled", True):
                try:
                    from sourcedock.core.notifications import send_desktop_notification

                    runner = getattr(self.application_registry, "runner", None)
                    send_desktop_notification(
                        t(lang, "updates_notification_title"),
                        t(lang, "updates_notification_body", count=len(items)),
                        runner=runner,
                    )
                except Exception:
                    pass
        else:

            self.updates_state.show_state(t(lang, "updates_empty"), t(lang, "updates_empty_body"))
        reboot_required = Path("/var/run/reboot-required").exists()
        self.updates_reboot_banner.set_text(t(lang, "updates_reboot_required") if reboot_required else "")
        self.updates_reboot_banner.set_visible(reboot_required)
        self._render_updates_status(provider_errors, error)
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
        if item is None:
            children = self.updates_model.iter_children(iterator)
            selectable = []
            while children is not None:
                child_item = self.updates_model.get_value(children, 5)
                if child_item is not None and child_item.application.update_supported:
                    selectable.append(children)
                children = self.updates_model.iter_next(children)
            target = not selectable or not all(self.updates_model.get_value(child, 0) for child in selectable)
            for child in selectable:
                self.updates_model.set_value(child, 0, target)
        elif item.application.update_supported:
            self.updates_model.set_value(iterator, 0, not self.updates_model.get_value(iterator, 0))
        self.updates_apply_btn.set_sensitive(bool(self._selected_updates()))
        self._refresh_selection_summary()

    def _on_updates_key_press(self, tree, event):
        if event.keyval not in (Gdk.KEY_space, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return Gdk.EVENT_PROPAGATE
        _model, paths = tree.get_selection().get_selected_rows()
        if not paths:
            return Gdk.EVENT_PROPAGATE
        self._on_update_toggled(None, paths[0].to_string())
        return Gdk.EVENT_STOP

    def _on_updates_button_press(self, tree, event):
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if event.button == 1 and hit:
            path = hit[0]
            if hit[1] is tree.get_column(0):
                return False
            iterator = self.updates_model.get_iter(path)
            item = self.updates_model.get_value(iterator, 5) if iterator is not None else None
            if item is not None and item.application.update_supported:
                tree.get_selection().select_path(path)
                self._on_update_toggled(None, path.to_string())
                return True
            if item is None and iterator is not None:
                self._on_update_toggled(None, path.to_string())
                return True
            return False
        if event.button != 3:
            return False
        if not hit:
            return False
        tree.get_selection().select_path(hit[0])
        return self._on_updates_popup_menu(tree, event)

    def _on_updates_popup_menu(self, tree, event=None):
        model, iterator = tree.get_selection().get_selected()
        item = model.get_value(iterator, 5) if iterator is not None else None
        if item is None or item.application.source != SOURCE_APT:
            return False
        menu = Gtk.Menu()
        changelog = Gtk.MenuItem(label=t(self.preferences.language, "changelog_menu"))
        changelog.connect("activate", lambda _item: self._on_package_changelog(item.application.package_name))
        menu.append(changelog)
        menu.show_all()
        if event is None:
            menu.popup_at_widget(tree, Gdk.Gravity.CENTER, Gdk.Gravity.CENTER, None)
        else:
            menu.popup_at_pointer(event)
        return True

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
        if getattr(self, "_syncing_updates_selection", False):
            return
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
        return show_firmware_confirmation(self, self.preferences.language)
