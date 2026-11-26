#!/usr/bin/env python3
"""Ayarlar (Tema, Dil, Güncelleme Politikası ve Sistem) görünümü ve diyaloğu."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.i18n import SUPPORTED_LANGUAGES, t
from sourcedock.preferences import AppPreferences
from sourcedock.core.errors import AuthRequiredError
from sourcedock.backend.mime_integration import is_default_package_handler, set_as_default_package_handler
from sourcedock.ui.components.common import prepare_dialog, set_status


def _disable_combo_scroll(combo: Gtk.ComboBoxText) -> None:
    """Fare tekerleğinin açılır kutu üzerinde gezinirken değeri değiştirmesini engeller."""
    combo.connect("scroll-event", lambda *_args: True)


class SettingsViewMixin:
    """Uygulama genel ayarlarını yöneten mixin."""

    def on_open_settings(self, _button: Gtk.Button) -> None:
        existing = getattr(self, "_settings_dialog", None)
        if existing is not None and not getattr(existing, "_closed", True):
            existing.present()
            return

        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "settings_title"),
            transient_for=None,
            modal=False,
            destroy_with_parent=False,
        )
        dialog._closed = False
        dialog.connect("destroy", lambda _w: setattr(dialog, "_closed", True))
        self._settings_dialog = dialog
        prepare_dialog(dialog, width=760, height=580, independent=True)
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)
        dialog.set_default_response(Gtk.ResponseType.CLOSE)

        outer = dialog.get_content_area()
        outer.set_spacing(10)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(14)
        outer.set_margin_end(14)

        subtitle = Gtk.Label(label=t(lang, "settings_subtitle"))
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        subtitle.get_style_context().add_class("dim-label")
        outer.pack_start(subtitle, False, False, 0)

        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        outer.pack_start(notebook, True, True, 0)

        def _make_tab(tab_title: str) -> Gtk.Box:
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            page.set_margin_top(14)
            page.set_margin_bottom(14)
            page.set_margin_start(14)
            page.set_margin_end(14)
            scroller.add(page)
            lbl = Gtk.Label(label=tab_title)
            lbl.set_margin_start(6)
            lbl.set_margin_end(6)
            lbl.set_margin_top(4)
            lbl.set_margin_bottom(4)
            notebook.append_page(scroller, lbl)
            return page

        # =====================================================================
        # SEKME 1: Genel & Görünüm
        # =====================================================================
        general_page = _make_tab(t(lang, "settings_tab_general"))

        form = Gtk.Grid(column_spacing=24, row_spacing=12)
        form.set_column_homogeneous(False)
        general_page.pack_start(form, False, False, 0)

        language_label = Gtk.Label(label=t(lang, "language"))
        language_label.set_xalign(0)
        language_label.set_size_request(190, -1)
        theme_label = Gtk.Label(label=t(lang, "theme"))
        theme_label.set_xalign(0)
        theme_label.set_size_request(190, -1)
        scale_label = Gtk.Label(label=t(lang, "ui_scale"))
        scale_label.set_xalign(0)
        scale_label.set_size_request(190, -1)

        language_combo = Gtk.ComboBoxText()
        language_combo.set_hexpand(True)
        language_combo.set_tooltip_text(t(lang, "tooltip_settings_language"))
        for language_code, language_name in SUPPORTED_LANGUAGES.items():
            language_combo.append(language_code, language_name)
        language_combo.set_active_id(self.preferences.language)
        _disable_combo_scroll(language_combo)

        theme_combo = Gtk.ComboBoxText()
        theme_combo.set_hexpand(True)
        theme_combo.set_tooltip_text(t(lang, "tooltip_settings_theme"))
        theme_combo.append("system", t(lang, "theme_system"))
        theme_combo.append("dark", t(lang, "theme_dark"))
        theme_combo.append("light", t(lang, "theme_light"))
        theme_combo.set_active_id(self.preferences.theme)
        _disable_combo_scroll(theme_combo)

        scale_combo = Gtk.ComboBoxText()
        scale_combo.set_hexpand(True)
        scale_combo.set_tooltip_text(t(lang, "tooltip_settings_scale"))
        scale_combo.append("90", t(lang, "scale_90"))
        scale_combo.append("100", t(lang, "scale_100"))
        scale_combo.append("110", t(lang, "scale_110"))
        scale_combo.append("125", t(lang, "scale_125"))
        scale_combo.set_active_id(getattr(self.preferences, "scale", "100"))
        _disable_combo_scroll(scale_combo)

        form.attach(language_label, 0, 0, 1, 1)
        form.attach(language_combo, 1, 0, 1, 1)
        form.attach(theme_label, 0, 1, 1, 1)
        form.attach(theme_combo, 1, 1, 1, 1)
        form.attach(scale_label, 0, 2, 1, 1)
        form.attach(scale_combo, 1, 2, 1, 1)

        source_label = Gtk.Label(label=t(lang, "settings_preferred_source"), xalign=0)
        source_label.set_size_request(190, -1)
        source_combo = Gtk.ComboBoxText()
        source_combo.set_hexpand(True)
        for source in ("all", self.store_registry.native_manager, "flatpak", "snap"):
            source_combo.append(source, t(lang, f"store_source_{source}"))
        source_combo.set_active_id(self.preferences.preferred_source)
        _disable_combo_scroll(source_combo)
        form.attach(source_label, 0, 3, 1, 1)
        form.attach(source_combo, 1, 3, 1, 1)

        sep_gen = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        general_page.pack_start(sep_gen, False, False, 2)

        notifications_check = Gtk.CheckButton(label=t(lang, "settings_notifications"))
        notifications_check.set_tooltip_text(t(lang, "settings_notifications_desc"))
        notifications_check.set_active(getattr(self.preferences, "notifications_enabled", True))
        general_page.pack_start(notifications_check, False, False, 0)

        detailed_table_check = Gtk.CheckButton(label=t(lang, "settings_detailed_table"))
        detailed_table_check.set_tooltip_text(t(lang, "settings_detailed_table_desc"))
        detailed_table_check.set_active(getattr(self.preferences, "detailed_table_default", True))
        general_page.pack_start(detailed_table_check, False, False, 0)

        show_technical_check = Gtk.CheckButton(label=t(lang, "settings_show_technical_packages"))
        show_technical_check.set_tooltip_text(t(lang, "settings_show_technical_packages_desc"))
        show_technical_check.set_active(getattr(self.preferences, "show_technical_packages", False))
        general_page.pack_start(show_technical_check, False, False, 0)

        operation_details_check = Gtk.CheckButton(
            label=t(lang, "settings_show_operation_details_by_default")
        )
        operation_details_check.set_tooltip_text(
            t(lang, "settings_show_operation_details_by_default_desc")
        )
        operation_details_check.set_active(
            getattr(self.preferences, "show_operation_details_by_default", False)
        )
        general_page.pack_start(operation_details_check, False, False, 0)

        # =====================================================================
        # SEKME 2: Güncelleme Politikası
        # =====================================================================
        updates_page = _make_tab(t(lang, "settings_tab_updates"))

        upd_title = Gtk.Label()
        upd_title.set_markup(f"<b>{GLib.markup_escape_text(t(lang, 'settings_update_policy_title'))}</b>")
        upd_title.set_xalign(0)
        updates_page.pack_start(upd_title, False, False, 0)

        upd_desc = Gtk.Label(label=t(lang, "settings_update_policy_desc"))
        upd_desc.set_xalign(0)
        upd_desc.set_line_wrap(True)
        upd_desc.get_style_context().add_class("dim-label")
        updates_page.pack_start(upd_desc, False, False, 0)

        updates_check = Gtk.CheckButton(label=t(lang, "settings_check_updates_start"))
        updates_check.set_active(self.preferences.check_updates_on_start)
        updates_page.pack_start(updates_check, False, False, 0)

        upd_card = Gtk.Frame()
        upd_card.get_style_context().add_class("summary-card")
        upd_card_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        upd_card_inner.set_margin_top(12)
        upd_card_inner.set_margin_bottom(12)
        upd_card_inner.set_margin_start(14)
        upd_card_inner.set_margin_end(14)
        upd_card.add(upd_card_inner)
        updates_page.pack_start(upd_card, False, False, 0)

        upd_grid = Gtk.Grid(column_spacing=24, row_spacing=10)
        upd_card_inner.pack_start(upd_grid, False, False, 0)

        schedule_options = (
            ("never", t(lang, "update_schedule_never")),
            ("on_start", t(lang, "update_schedule_on_start")),
            ("hourly", t(lang, "update_schedule_hourly")),
            ("daily", t(lang, "update_schedule_daily")),
            ("weekly", t(lang, "update_schedule_weekly")),
        )

        def _make_schedule_combo(current_val: str) -> Gtk.ComboBoxText:
            combo = Gtk.ComboBoxText()
            for opt_id, opt_label in schedule_options:
                combo.append(opt_id, opt_label)
            combo.set_active_id(current_val if current_val in {o[0] for o in schedule_options} else "never")
            combo.set_hexpand(True)
            _disable_combo_scroll(combo)
            return combo

        native_mgr = getattr(self.store_registry, "native_manager", "apt")
        native_lbl = Gtk.Label(label=t(lang, f"store_source_{native_mgr}"), xalign=0)
        native_lbl.set_size_request(190, -1)
        native_sched_combo = _make_schedule_combo(getattr(self.preferences, "update_schedule_native", "never"))
        upd_grid.attach(native_lbl, 0, 0, 1, 1)
        upd_grid.attach(native_sched_combo, 1, 0, 1, 1)

        flatpak_lbl = Gtk.Label(label=t(lang, "store_source_flatpak"), xalign=0)
        flatpak_lbl.set_size_request(190, -1)
        flatpak_sched_combo = _make_schedule_combo(getattr(self.preferences, "update_schedule_flatpak", "never"))
        upd_grid.attach(flatpak_lbl, 0, 1, 1, 1)
        upd_grid.attach(flatpak_sched_combo, 1, 1, 1, 1)

        snap_lbl = Gtk.Label(label=t(lang, "store_source_snap"), xalign=0)
        snap_lbl.set_size_request(190, -1)
        snap_sched_combo = _make_schedule_combo(getattr(self.preferences, "update_schedule_snap", "never"))
        upd_grid.attach(snap_lbl, 0, 2, 1, 1)
        upd_grid.attach(snap_sched_combo, 1, 2, 1, 1)

        # Snap sistem otomatik güncelleme kontrolü (snapd hold)
        registry = getattr(self, "application_registry", None)
        snap_paused_state = (
            registry.get_snap_auto_refresh_paused()
            if registry and hasattr(registry, "get_snap_auto_refresh_paused")
            else None
        )

        snap_hold_card = Gtk.Frame()
        snap_hold_card.get_style_context().add_class("summary-card")
        snap_hold_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        snap_hold_inner.set_margin_top(12)
        snap_hold_inner.set_margin_bottom(12)
        snap_hold_inner.set_margin_start(14)
        snap_hold_inner.set_margin_end(14)
        snap_hold_card.add(snap_hold_inner)
        updates_page.pack_start(snap_hold_card, False, False, 0)

        snap_hold_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        snap_hold_title = Gtk.Label(xalign=0)
        snap_hold_title.set_markup(f"<b>{t(lang, 'settings_snap_auto_refresh_pause')}</b>")
        snap_hold_desc = Gtk.Label(label=t(lang, "settings_snap_auto_refresh_desc"), xalign=0)
        snap_hold_desc.set_line_wrap(True)
        snap_hold_desc.get_style_context().add_class("dim-label")
        snap_hold_status = Gtk.Label(xalign=0)
        snap_hold_status.set_line_wrap(True)
        snap_hold_text_box.pack_start(snap_hold_title, False, False, 0)
        snap_hold_text_box.pack_start(snap_hold_desc, False, False, 0)
        snap_hold_text_box.pack_start(snap_hold_status, False, False, 0)
        snap_hold_inner.pack_start(snap_hold_text_box, True, True, 0)

        snap_hold_switch = Gtk.Switch()
        snap_hold_switch.set_valign(Gtk.Align.CENTER)
        snap_hold_inner.pack_end(snap_hold_switch, False, False, 0)

        def _update_snap_hold_status_label(paused_val: bool | None) -> None:
            if paused_val is None:
                snap_hold_status.set_text(t(lang, "settings_snap_auto_refresh_unavailable"))
                snap_hold_status.get_style_context().add_class("dim-label")
            elif paused_val:
                snap_hold_status.set_text(t(lang, "settings_snap_auto_refresh_paused_status"))
                snap_hold_status.get_style_context().remove_class("dim-label")
                snap_hold_status.get_style_context().add_class("success-text")
            else:
                snap_hold_status.set_text(t(lang, "settings_snap_auto_refresh_active_status"))
                snap_hold_status.get_style_context().remove_class("success-text")
                snap_hold_status.get_style_context().add_class("dim-label")

        _snap_hold_guard = {"updating": True}
        if snap_paused_state is None:
            snap_hold_switch.set_sensitive(False)
            snap_hold_switch.set_active(False)
        else:
            snap_hold_switch.set_active(bool(snap_paused_state))
        _update_snap_hold_status_label(snap_paused_state)
        _snap_hold_guard["updating"] = False

        def _on_snap_hold_state_set(_sw, state: bool) -> bool:
            if _snap_hold_guard["updating"] or registry is None:
                return False
            desired = bool(state)
            try:
                try:
                    registry.set_snap_auto_refresh_paused(desired)
                except AuthRequiredError as auth_err:
                    pwd = self._ask_sudo_password(retry=getattr(auth_err, "password_failed", False))
                    if not pwd:
                        raise auth_err
                    registry.runner.set_sudo_password(pwd)
                    registry.set_snap_auto_refresh_paused(desired)
                _update_snap_hold_status_label(desired)
                return False
            except Exception as exc:
                _snap_hold_guard["updating"] = True
                snap_hold_switch.set_active(not desired)
                _snap_hold_guard["updating"] = False
                set_status(snap_hold_status, str(exc), error=True)
                return True

        snap_hold_switch.connect("state-set", _on_snap_hold_state_set)

        # =====================================================================
        # SEKME 3: Sistem ve Kaynaklar
        # =====================================================================
        system_page = _make_tab(t(lang, "settings_tab_system"))

        sources_card = Gtk.Frame()
        sources_card.get_style_context().add_class("summary-card")
        sources_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        sources_box.set_margin_top(12)
        sources_box.set_margin_bottom(12)
        sources_box.set_margin_start(14)
        sources_box.set_margin_end(14)
        sources_card.add(sources_box)

        sources_lbl = Gtk.Label(xalign=0)
        sources_lbl.set_markup(f"<b>{t(lang, 'settings_sources')}</b>")
        sources_box.pack_start(sources_lbl, True, True, 0)

        def _raise_settings() -> None:
            if not getattr(dialog, "_closed", True):
                dialog.present()

        sources_button = Gtk.Button(label=t(lang, "settings_sources"))
        sources_button.get_style_context().add_class("secondary-action")
        sources_button.connect("clicked", lambda _b: self.on_open_sources(on_close=_raise_settings))
        sources_box.pack_end(sources_button, False, False, 0)
        system_page.pack_start(sources_card, False, False, 0)

        # Yedekleme, Geri Yükleme ve Disk Temizliği Kartı
        tools_card = Gtk.Frame()
        tools_card.get_style_context().add_class("summary-card")
        tools_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tools_box.set_margin_top(12)
        tools_box.set_margin_bottom(12)
        tools_box.set_margin_start(14)
        tools_box.set_margin_end(14)
        tools_card.add(tools_box)

        tools_title = Gtk.Label(xalign=0)
        tools_title.set_markup(f"<b>{GLib.markup_escape_text(t(lang, 'settings_backup_cleanup_title'))}</b>")
        tools_box.pack_start(tools_title, False, False, 0)

        tools_desc = Gtk.Label(label=t(lang, "settings_backup_cleanup_desc"), xalign=0)
        tools_desc.set_line_wrap(True)
        tools_desc.get_style_context().add_class("dim-label")
        tools_box.pack_start(tools_desc, False, False, 0)

        tools_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tools_box.pack_start(tools_btn_row, False, False, 0)

        export_btn = Gtk.Button(label=t(lang, "applications_export"))
        export_btn.get_style_context().add_class("secondary-action")
        export_btn.connect(
            "clicked",
            lambda _b: self.on_export_application_list(on_close=_raise_settings)
            if hasattr(self, "on_export_application_list")
            else None,
        )
        tools_btn_row.pack_start(export_btn, False, False, 0)

        restore_btn = Gtk.Button(label=t(lang, "restore_title"))
        restore_btn.get_style_context().add_class("secondary-action")
        restore_btn.connect(
            "clicked",
            lambda _b: self.on_import_application_list(on_close=_raise_settings)
            if hasattr(self, "on_import_application_list")
            else None,
        )
        tools_btn_row.pack_start(restore_btn, False, False, 0)

        cleanup_btn = Gtk.Button(label=t(lang, "cleanup_dialog_title"))
        cleanup_btn.get_style_context().add_class("secondary-action")
        cleanup_btn.connect(
            "clicked",
            lambda _b: self.on_open_disk_cleanup(on_close=_raise_settings)
            if hasattr(self, "on_open_disk_cleanup")
            else None,
        )
        tools_btn_row.pack_start(cleanup_btn, False, False, 0)
        system_page.pack_start(tools_card, False, False, 0)

        sys_card = Gtk.Frame()
        sys_card.get_style_context().add_class("summary-card")
        sys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sys_box.set_margin_top(12)
        sys_box.set_margin_bottom(12)
        sys_box.set_margin_start(14)
        sys_box.set_margin_end(14)
        sys_card.add(sys_box)
        system_page.pack_start(sys_card, False, False, 0)

        sys_title = Gtk.Label()
        sys_title.set_markup(f"<b>{t(lang, 'settings_system_integration')}</b>")
        sys_title.set_xalign(0)
        sys_box.pack_start(sys_title, False, False, 0)

        sys_desc = Gtk.Label(label=t(lang, "settings_default_installer_desc"))
        sys_desc.set_xalign(0)
        sys_desc.set_line_wrap(True)
        sys_desc.get_style_context().add_class("dim-label")
        sys_box.pack_start(sys_desc, False, False, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sys_box.pack_start(action_box, False, False, 0)

        status_lbl = Gtk.Label()
        status_lbl.set_xalign(0)
        status_lbl.set_line_wrap(True)

        is_def = is_default_package_handler()
        btn_label = t(lang, "settings_already_default_btn") if is_def else t(lang, "settings_set_default_btn")
        set_default_btn = Gtk.Button(label=btn_label)
        set_default_btn.get_style_context().add_class("secondary-action")
        set_default_btn.set_tooltip_text(t(lang, "tooltip_settings_set_default"))

        def on_set_default_clicked(_btn):
            ok, msg = set_as_default_package_handler()
            if ok:
                set_default_btn.set_label(t(lang, "settings_already_default_btn"))
                set_default_btn.get_style_context().remove_class("suggested-action")
                set_status(status_lbl, t(lang, "settings_default_success"))
            else:
                set_status(status_lbl, msg, error=True)

        set_default_btn.connect("clicked", on_set_default_clicked)
        action_box.pack_start(set_default_btn, False, False, 0)
        action_box.pack_start(status_lbl, True, True, 0)

        _save_guard = {"initializing": True}

        def _apply_and_save_settings(*_args, refresh_ui: bool = False, refresh_theme: bool = False, refresh_apps: bool = False, refresh_store: bool = False) -> None:
            if _save_guard["initializing"]:
                return
            new_lang = language_combo.get_active_id() or self.preferences.language
            new_theme = theme_combo.get_active_id() or self.preferences.theme
            new_scale = scale_combo.get_active_id() or getattr(self.preferences, "scale", "100")
            self.preferences = AppPreferences(
                language=new_lang,
                theme=new_theme,
                scale=new_scale,
                preferred_source=source_combo.get_active_id() or "all",
                check_updates_on_start=updates_check.get_active(),
                notifications_enabled=notifications_check.get_active(),
                detailed_table_default=detailed_table_check.get_active(),
                show_technical_packages=show_technical_check.get_active(),
                show_operation_details_by_default=operation_details_check.get_active(),
                update_schedule_native=native_sched_combo.get_active_id() or "never",
                update_schedule_flatpak=flatpak_sched_combo.get_active_id() or "never",
                update_schedule_snap=snap_sched_combo.get_active_id() or "never",
                last_update_check_native=getattr(self.preferences, "last_update_check_native", 0.0),
                last_update_check_flatpak=getattr(self.preferences, "last_update_check_flatpak", 0.0),
                last_update_check_snap=getattr(self.preferences, "last_update_check_snap", 0.0),
            )
            self.preferences_store.save(self.preferences)
            if refresh_theme:
                self._apply_theme()
            if refresh_ui:
                self._refresh_texts()
            if refresh_apps:
                if hasattr(self, "applications_table_toggle") and self.applications_table_toggle is not None:
                    self.applications_table_toggle.set_active(self.preferences.detailed_table_default)
                if hasattr(self, "_update_application_list_ui"):
                    self._update_application_list_ui()
            if refresh_store:
                button = self.store_filter_buttons.get(self.preferences.preferred_source)
                if button:
                    button.set_active(True)
                self._render_store_results(self.store_results)

        _save_guard["initializing"] = False
        language_combo.connect("changed", lambda _w: _apply_and_save_settings(refresh_ui=True, refresh_theme=True, refresh_apps=True, refresh_store=True))
        theme_combo.connect("changed", lambda _w: _apply_and_save_settings(refresh_theme=True))
        scale_combo.connect("changed", lambda _w: _apply_and_save_settings(refresh_theme=True))
        source_combo.connect("changed", lambda _w: _apply_and_save_settings(refresh_store=True))
        updates_check.connect("toggled", lambda _w: _apply_and_save_settings())
        notifications_check.connect("toggled", lambda _w: _apply_and_save_settings())
        detailed_table_check.connect("toggled", lambda _w: _apply_and_save_settings(refresh_apps=True))
        show_technical_check.connect("toggled", lambda _w: _apply_and_save_settings(refresh_apps=True, refresh_store=True))
        operation_details_check.connect("toggled", lambda _w: _apply_and_save_settings())
        native_sched_combo.connect("changed", lambda _w: _apply_and_save_settings())
        flatpak_sched_combo.connect("changed", lambda _w: _apply_and_save_settings())
        snap_sched_combo.connect("changed", lambda _w: _apply_and_save_settings())

        dialog.connect("response", lambda _diag, _resp: dialog.destroy())
        dialog.show_all()
