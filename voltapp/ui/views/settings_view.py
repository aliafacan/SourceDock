#!/usr/bin/env python3
"""Ayarlar (Tema ve Dil) görünümü ve diyaloğu."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # pyright: ignore[reportMissingModuleSource]

from voltapp.i18n import t
from voltapp.preferences import AppPreferences


class SettingsViewMixin:
    """Uygulama genel ayarlarını yöneten mixin."""

    def on_open_settings(self, _button: Gtk.Button) -> None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "settings_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(self.preferences.language, "settings_save"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        subtitle = Gtk.Label(label=t(self.preferences.language, "settings_subtitle"))
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        content.pack_start(subtitle, False, False, 0)

        form = Gtk.Grid(column_spacing=12, row_spacing=12)
        content.pack_start(form, False, False, 0)

        language_label = Gtk.Label(label=t(self.preferences.language, "language"))
        language_label.set_xalign(0)
        theme_label = Gtk.Label(label=t(self.preferences.language, "theme"))
        theme_label.set_xalign(0)

        language_combo = Gtk.ComboBoxText()
        language_combo.append("tr", t(self.preferences.language, "language_tr"))
        language_combo.append("en", t(self.preferences.language, "language_en"))
        language_combo.set_active_id(self.preferences.language)

        theme_combo = Gtk.ComboBoxText()
        theme_combo.append("dark", t(self.preferences.language, "theme_dark"))
        theme_combo.append("light", t(self.preferences.language, "theme_light"))
        theme_combo.set_active_id(self.preferences.theme)

        form.attach(language_label, 0, 0, 1, 1)
        form.attach(language_combo, 1, 0, 1, 1)
        form.attach(theme_label, 0, 1, 1, 1)
        form.attach(theme_combo, 1, 1, 1, 1)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_lang = language_combo.get_active_id() or self.preferences.language
            new_theme = theme_combo.get_active_id() or self.preferences.theme
            self.preferences = AppPreferences(language=new_lang, theme=new_theme)
            self.preferences_store.save(self.preferences)
            self._apply_theme()
            self._refresh_texts()
        dialog.destroy()
