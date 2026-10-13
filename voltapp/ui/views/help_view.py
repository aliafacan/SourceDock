#!/usr/bin/env python3
"""Yardım ve Kullanım Kılavuzu görünümü ve diyaloğu (HelpDialog & HelpViewMixin)."""

from __future__ import annotations

import os

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from voltapp.backend.mime_integration import get_icon_path
from voltapp.i18n import t


class HelpDialog(Gtk.Dialog):
    """VoltApp sistem geneli yardım ve kullanım kılavuzu penceresi."""

    def __init__(self, parent: Gtk.Window | None = None, language: str = "tr"):
        super().__init__(
            title=t(language, "help_title"),
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL if parent else 0,
        )
        self.language = language

        self.set_default_size(720, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")

        # İkon
        icon_file = get_icon_path()
        if os.path.exists(icon_file):
            try:
                self.set_icon_from_file(icon_file)
            except Exception:
                pass

        self.connect("key-press-event", self._on_key_press)
        self._build_ui()

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        key = Gdk.keyval_name(event.keyval) or ""
        if key == "Escape":
            self.response(Gtk.ResponseType.CLOSE)
            return True
        return False

    def _build_ui(self) -> None:
        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(18)
        content.set_margin_end(18)

        # Başlık ve Açıklama
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.pack_start(header_box, False, False, 0)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(
            f'<span size="x-large" weight="bold">{GLib.markup_escape_text(t(self.language, "help_title"))}</span>'
        )
        title_lbl.set_xalign(0)
        header_box.pack_start(title_lbl, False, False, 0)

        sub_lbl = Gtk.Label(label=t(self.language, "help_subtitle"))
        sub_lbl.set_xalign(0)
        sub_lbl.get_style_context().add_class("dim-label")
        header_box.pack_start(sub_lbl, False, False, 0)

        # Stack & StackSwitcher
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(6)
        switcher.set_margin_bottom(6)
        content.pack_start(switcher, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        # 1. Genel Bakış Sayfası
        self._build_overview_page()

        # 2. Sekmeler & Özellikler Sayfası
        self._build_features_page()

        # 3. Mini Kurucu & Sürüm Analizi Sayfası
        self._build_installer_page()

        # 4. Kısayollar & İpuçları Sayfası
        self._build_shortcuts_page()

        content.pack_start(self.stack, True, True, 0)

        # Alt Buton
        close_btn = self.add_button(t(self.language, "dialog_close"), Gtk.ResponseType.CLOSE)
        close_btn.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.CLOSE)

        self.show_all()

    def _create_scroll_page(self) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_margin_top(8)
        vbox.set_margin_bottom(8)
        vbox.set_margin_start(6)
        vbox.set_margin_end(10)
        scroller.add(vbox)
        return scroller, vbox

    def _create_card(self, title: str, content_markup: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("card")

        t_lbl = Gtk.Label()
        t_lbl.set_markup(f'<span weight="bold" size="medium">{GLib.markup_escape_text(title)}</span>')
        t_lbl.set_xalign(0)
        card.pack_start(t_lbl, False, False, 0)

        c_lbl = Gtk.Label()
        c_lbl.set_markup(content_markup)
        c_lbl.set_line_wrap(True)
        c_lbl.set_xalign(0)
        card.pack_start(c_lbl, False, False, 0)

        return card

    def _build_overview_page(self) -> None:
        scroller, box = self._create_scroll_page()

        # Nedir kartı
        box.pack_start(
            self._create_card(
                t(self.language, "help_overview_what_title"),
                GLib.markup_escape_text(t(self.language, "help_overview_what_desc")),
            ),
            False,
            False,
            0,
        )

        # Formatlar kartı
        formats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        formats_box.get_style_context().add_class("card")

        f_title = Gtk.Label()
        f_title.set_markup(
            f'<span weight="bold" size="medium">{GLib.markup_escape_text(t(self.language, "help_overview_formats_title"))}</span>'
        )
        f_title.set_xalign(0)
        formats_box.pack_start(f_title, False, False, 0)

        fmt_keys = [
            "help_overview_fmt_native",
            "help_overview_fmt_flatpak",
            "help_overview_fmt_snap",
            "help_overview_fmt_appimage",
            "help_overview_fmt_portable",
            "help_overview_fmt_local",
        ]
        for key in fmt_keys:
            item_lbl = Gtk.Label()
            item_lbl.set_markup(t(self.language, key))
            item_lbl.set_line_wrap(True)
            item_lbl.set_xalign(0)
            item_lbl.set_margin_start(6)
            formats_box.pack_start(item_lbl, False, False, 0)

        box.pack_start(formats_box, False, False, 0)

        # Güvenlik kartı
        box.pack_start(
            self._create_card(
                t(self.language, "help_overview_security_title"),
                GLib.markup_escape_text(t(self.language, "help_overview_security_desc")),
            ),
            False,
            False,
            0,
        )

        self.stack.add_titled(scroller, "overview", t(self.language, "help_tab_overview"))

    def _build_features_page(self) -> None:
        scroller, box = self._create_scroll_page()

        features = [
            ("help_features_installed_title", "help_features_installed_desc"),
            ("help_features_store_title", "help_features_store_desc"),
            ("help_features_packages_title", "help_features_packages_desc"),
            ("help_features_operations_title", "help_features_operations_desc"),
        ]
        for title_key, desc_key in features:
            box.pack_start(
                self._create_card(t(self.language, title_key), t(self.language, desc_key)),
                False,
                False,
                0,
            )

        self.stack.add_titled(scroller, "features", t(self.language, "help_tab_features"))

    def _build_installer_page(self) -> None:
        scroller, box = self._create_scroll_page()

        installer_sections = [
            ("help_installer_mini_title", "help_installer_mini_desc"),
            ("help_installer_smart_title", "help_installer_smart_desc"),
            ("help_installer_flow_title", "help_installer_flow_desc"),
        ]
        for title_key, desc_key in installer_sections:
            box.pack_start(
                self._create_card(t(self.language, title_key), t(self.language, desc_key)),
                False,
                False,
                0,
            )

        self.stack.add_titled(scroller, "installer", t(self.language, "help_tab_installer"))

    def _build_shortcuts_page(self) -> None:
        scroller, box = self._create_scroll_page()

        # Kısayollar Tablosu Kartı
        shortcuts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        shortcuts_box.get_style_context().add_class("card")

        s_title = Gtk.Label()
        s_title.set_markup(
            f'<span weight="bold" size="medium">{GLib.markup_escape_text(t(self.language, "help_shortcuts_title"))}</span>'
        )
        s_title.set_xalign(0)
        shortcuts_box.pack_start(s_title, False, False, 0)

        grid = Gtk.Grid()
        grid.set_column_spacing(20)
        grid.set_row_spacing(8)
        grid.set_margin_start(6)
        shortcuts_box.pack_start(grid, False, False, 0)

        shortcut_items = [
            ("F1", "help_shortcuts_f1"),
            ("Ctrl + F", "help_shortcuts_ctrl_f"),
            ("F5", "help_shortcuts_f5"),
            ("Delete", "help_shortcuts_delete"),
            ("Esc", "help_shortcuts_escape"),
        ]

        for row, (key_label, desc_key) in enumerate(shortcut_items):
            key_pill = Gtk.Label()
            key_pill.set_markup(f'<tt><b>[ {key_label} ]</b></tt>')
            key_pill.set_xalign(0)

            desc_lbl = Gtk.Label(label=t(self.language, desc_key))
            desc_lbl.set_xalign(0)

            grid.attach(key_pill, 0, row, 1, 1)
            grid.attach(desc_lbl, 1, row, 1, 1)

        box.pack_start(shortcuts_box, False, False, 0)

        # İpuçları Kartı
        tips_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tips_box.get_style_context().add_class("card")

        t_title = Gtk.Label()
        t_title.set_markup(
            f'<span weight="bold" size="medium">{GLib.markup_escape_text(t(self.language, "help_tips_title"))}</span>'
        )
        t_title.set_xalign(0)
        tips_box.pack_start(t_title, False, False, 0)

        tips = ["help_tips_dnd", "help_tips_default", "help_tips_appimage"]
        for key in tips:
            tip_lbl = Gtk.Label()
            tip_lbl.set_markup(t(self.language, key))
            tip_lbl.set_line_wrap(True)
            tip_lbl.set_xalign(0)
            tip_lbl.set_margin_start(6)
            tips_box.pack_start(tip_lbl, False, False, 0)

        box.pack_start(tips_box, False, False, 0)

        self.stack.add_titled(scroller, "shortcuts", t(self.language, "help_tab_shortcuts"))


class HelpViewMixin:
    """Yardım ve kullanım kılavuzu diyaloğunu yöneten mixin."""

    def on_open_help(self, _button: Gtk.Button | None = None) -> None:
        dialog = HelpDialog(parent=self, language=self.preferences.language)
        dialog.run()
        dialog.destroy()

