#!/usr/bin/env python3
"""Yerel paket önizleme ve kurulum diyaloğu (PackageInstallerDialog)."""

from __future__ import annotations

import os
from pathlib import Path

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from voltapp.core.models import LocalPackageInfo
from voltapp.i18n import t


class PackageInstallerDialog(Gtk.Dialog):
    """Yerel bir paketin (.deb, .AppImage, arşiv, vb.) metaverilerini gösterip kurulum onayını alan diyalog."""

    def __init__(
        self,
        parent: Gtk.Window,
        info: LocalPackageInfo,
        language: str = "tr",
        is_installed: bool = False,
    ):
        super().__init__(
            title=t(language, "package_installer_title"),
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.info = info
        self.language = language
        self.is_installed = is_installed
        self.is_reinstall = is_installed
        self.set_default_size(520, 440)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")

        self.add_button(t(language, "password_cancel"), Gtk.ResponseType.CANCEL)
        action_label = (
            t(language, "package_installer_reinstall_btn")
            if is_installed
            else t(language, "package_installer_install_btn")
        )
        install_btn = self.add_button(action_label, Gtk.ResponseType.OK)
        install_btn.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        self.create_desktop_check: Gtk.CheckButton | None = None
        self.copy_to_apps_check: Gtk.CheckButton | None = None
        self.delete_after_check: Gtk.CheckButton | None = None
        self.flatpak_scope_user_radio: Gtk.RadioButton | None = None
        self.flatpak_scope_system_radio: Gtk.RadioButton | None = None

        self._build_ui()
        self.show_all()

    def _build_ui(self) -> None:
        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        # 1. Başlık ve İkon Alanı
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        content.pack_start(header_box, False, False, 0)

        icon_widget = self._create_icon_widget()
        header_box.pack_start(icon_widget, False, False, 0)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.pack_start(title_vbox, True, True, 0)

        # Başlık ve Format Rozeti
        name_badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_vbox.pack_start(name_badge_box, False, False, 0)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(f'<span size="x-large" weight="bold">{GLib.markup_escape_text(self.info.name)}</span>')
        title_lbl.set_xalign(0)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_badge_box.pack_start(title_lbl, False, False, 0)

        badge_lbl = Gtk.Label()
        badge_text, badge_color = self._format_badge()
        badge_lbl.set_markup(
            f'<span foreground="white" background="{badge_color}" weight="bold">  {badge_text}  </span>'
        )
        badge_lbl.set_valign(Gtk.Align.CENTER)
        name_badge_box.pack_start(badge_lbl, False, False, 0)

        if self.is_installed:
            inst_badge = Gtk.Label()
            inst_badge.set_markup(
                f'<span foreground="#065f46" background="#a7f3d0" weight="bold">  ✓ {t(self.language, "package_installer_already_installed_badge")}  </span>'
            )
            inst_badge.set_valign(Gtk.Align.CENTER)
            name_badge_box.pack_start(inst_badge, False, False, 0)

        if self.info.version:
            ver_lbl = Gtk.Label()
            ver_lbl.set_markup(f'<span foreground="#888888">v{GLib.markup_escape_text(self.info.version)}</span>')
            ver_lbl.set_xalign(0)
            title_vbox.pack_start(ver_lbl, False, False, 0)

        if self.info.summary:
            summary_lbl = Gtk.Label(label=self.info.summary)
            summary_lbl.set_line_wrap(True)
            summary_lbl.set_xalign(0)
            summary_lbl.get_style_context().add_class("dim-label")
            title_vbox.pack_start(summary_lbl, False, False, 0)

        if self.is_installed:
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_lbl = Gtk.Label()
            hint_lbl.set_markup(
                f'<span foreground="#059669">ℹ {t(self.language, "package_installer_already_installed_hint")}</span>'
            )
            hint_lbl.set_line_wrap(True)
            hint_lbl.set_xalign(0)
            hint_box.pack_start(hint_lbl, True, True, 0)
            content.pack_start(hint_box, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        # 2. Detay Bilgileri Tablosu
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(6)
        content.pack_start(grid, False, False, 0)

        row = 0
        file_size_str = self._format_file_size(self.info.size_bytes)
        row = self._add_grid_row(grid, row, t(self.language, "packages_col_size") + ":", file_size_str)

        if self.info.installed_size:
            row = self._add_grid_row(grid, row, t(self.language, "package_installer_installed_size") + ":", self.info.installed_size)

        if self.info.architecture:
            row = self._add_grid_row(grid, row, t(self.language, "package_installer_arch") + ":", self.info.architecture)

        if self.info.maintainer:
            row = self._add_grid_row(grid, row, t(self.language, "package_installer_maintainer") + ":", self.info.maintainer)

        fn = Path(self.info.file_path).name
        row = self._add_grid_row(grid, row, t(self.language, "package_installer_file") + ":", fn)

        # 3. Açıklama & Bağımlılıklar (Scrolled)
        if self.info.description or self.info.dependencies:
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_min_content_height(100)
            scrolled.get_style_context().add_class("frame")

            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.set_left_margin(8)
            tv.set_right_margin(8)
            tv.set_top_margin(8)
            tv.set_bottom_margin(8)

            body_lines = []
            if self.info.description:
                body_lines.append(self.info.description)
            if self.info.dependencies:
                deps_title = t(self.language, "package_installer_deps")
                body_lines.append(f"\n[{deps_title}]")
                body_lines.extend(f" • {d}" for d in self.info.dependencies)

            tv.get_buffer().set_text("\n".join(body_lines))
            scrolled.add(tv)
            content.pack_start(scrolled, True, True, 0)

        # 4. Kurulum Seçenekleri
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.pack_start(options_box, False, False, 0)

        if self.info.format in ("appimage", "archive"):
            self.create_desktop_check = Gtk.CheckButton(label=t(self.language, "package_installer_create_shortcut"))
            self.create_desktop_check.set_active(True)
            options_box.pack_start(self.create_desktop_check, False, False, 0)

        if self.info.format == "appimage":
            self.copy_to_apps_check = Gtk.CheckButton(label=t(self.language, "package_installer_copy_apps"))
            self.copy_to_apps_check.set_active(True)
            options_box.pack_start(self.copy_to_apps_check, False, False, 0)

        if self.info.format in ("deb", "rpm", "flatpak", "flatpakref", "archive"):
            self.delete_after_check = Gtk.CheckButton(label=t(self.language, "package_installer_delete_after"))
            self.delete_after_check.set_active(False)
            options_box.pack_start(self.delete_after_check, False, False, 0)

        if self.info.format in ("flatpak", "flatpakref"):
            scope_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            scope_box.set_margin_top(4)
            scope_lbl = Gtk.Label(label=t(self.language, "package_installer_scope_title") + ":")
            scope_lbl.set_xalign(0)
            scope_lbl.get_style_context().add_class("dim-label")
            scope_box.pack_start(scope_lbl, False, False, 0)

            self.flatpak_scope_user_radio = Gtk.RadioButton.new_with_label(
                None, t(self.language, "package_installer_scope_user")
            )
            self.flatpak_scope_system_radio = Gtk.RadioButton.new_with_label_from_widget(
                self.flatpak_scope_user_radio, t(self.language, "package_installer_scope_system")
            )
            self.flatpak_scope_user_radio.set_active(True)
            scope_box.pack_start(self.flatpak_scope_user_radio, False, False, 0)
            scope_box.pack_start(self.flatpak_scope_system_radio, False, False, 0)
            options_box.pack_start(scope_box, False, False, 0)

    def _create_icon_widget(self) -> Gtk.Widget:
        icon_path = self.info.icon
        if icon_path and os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 48, 48, True)
                return Gtk.Image.new_from_pixbuf(pixbuf)
            except Exception:
                pass

        icon_theme = Gtk.IconTheme.get_default()
        icon_name = icon_path or "package-x-generic"
        if not icon_theme.has_icon(icon_name):
            icon_name = "package-x-generic"
        img = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        img.set_pixel_size(48)
        return img

    def _format_badge(self) -> tuple[str, str]:
        badges = {
            "deb": ("DEB", "#2b78e4"),
            "appimage": ("AppImage", "#7b42bc"),
            "archive": ("PORTABLE", "#d97706"),
            "flatpakref": ("Flatpak", "#329932"),
            "flatpak": ("Flatpak", "#329932"),
            "rpm": ("RPM", "#c2410c"),
        }
        return badges.get(self.info.format, (self.info.format.upper(), "#6b7280"))

    def _format_file_size(self, size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"

    def _add_grid_row(self, grid: Gtk.Grid, row: int, label_text: str, value_text: str) -> int:
        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0)
        lbl.get_style_context().add_class("dim-label")
        grid.attach(lbl, 0, row, 1, 1)

        val = Gtk.Label(label=value_text)
        val.set_xalign(0)
        val.set_ellipsize(Pango.EllipsizeMode.END)
        grid.attach(val, 1, row, 1, 1)
        return row + 1

    @property
    def should_create_desktop(self) -> bool:
        return self.create_desktop_check.get_active() if self.create_desktop_check else True

    @property
    def should_copy_to_applications(self) -> bool:
        return self.copy_to_apps_check.get_active() if self.copy_to_apps_check else False

    @property
    def flatpak_scope(self) -> str:
        if self.flatpak_scope_system_radio and self.flatpak_scope_system_radio.get_active():
            return "--system"
        return "--user"

    @property
    def should_reinstall(self) -> bool:
        return self.is_reinstall

    @property
    def should_delete_installer(self) -> bool:
        return self.delete_after_check.get_active() if self.delete_after_check else False



