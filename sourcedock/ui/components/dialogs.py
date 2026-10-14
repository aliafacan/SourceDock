#!/usr/bin/env python3
"""Yeniden kullanılabilir arayüz diyalogları (Detay, Şifre, Snap Classic vb.)."""

from __future__ import annotations

from collections.abc import Callable
import json
import re
import threading
import urllib.request

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.models import SOURCE_FLATPAK, StoreResult
from sourcedock.i18n import t


class AppDetailDialog(Gtk.Dialog):
    """Uygulama detay, ekran görüntüsü ve kurulum diyaloğu."""

    def __init__(
        self,
        primary_result: StoreResult,
        all_results: list[StoreResult],
        installed_package_ids: set[str],
        install_callback: Callable[[StoreResult], None],
        language: str,
        parent: Gtk.Window,
    ) -> None:
        super().__init__(
            title=primary_result.name,
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.set_default_size(740, 580)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")

        self._primary = primary_result
        self._installed_ids = installed_package_ids
        self._install_callback = install_callback
        self._language = language
        self._selected_result = primary_result
        self._source_combo: Gtk.ComboBoxText | None = None

        seen_sources: set[str] = {primary_result.source}
        self._alternates: list[StoreResult] = []
        for r in all_results:
            if r.source not in seen_sources and (
                (primary_result.identity and r.identity == primary_result.identity)
                or (
                    not primary_result.identity
                    and not r.identity
                    and re.sub(r"[^a-z0-9.+:-]+", "", r.app_id.casefold())
                    == re.sub(r"[^a-z0-9.+:-]+", "", primary_result.app_id.casefold())
                )
            ):
                self._alternates.append(r)
                seen_sources.add(r.source)

        if primary_result.source == SOURCE_FLATPAK:
            self._flatpak_app_id: str | None = primary_result.app_id
        else:
            alt_fp = next((a for a in self._alternates if a.source == SOURCE_FLATPAK), None)
            self._flatpak_app_id = alt_fp.app_id if alt_fp else None

        self._build_content()
        self.connect("response", lambda _d, _r: self.destroy())
        self.show_all()

        if self._flatpak_app_id:
            threading.Thread(target=self._load_screenshots_async, daemon=True).start()

    def _build_content(self) -> None:
        content = self.get_content_area()
        content.set_spacing(0)

        outer_scroll = Gtk.ScrolledWindow()
        outer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer_scroll.set_min_content_height(420)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(16)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)

        self._icon_image = Gtk.Image()
        self._icon_image.set_pixel_size(96)
        self._icon_image.set_valign(Gtk.Align.START)
        self._load_icon(self._primary, 96)
        header_box.pack_start(self._icon_image, False, False, 0)

        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info_vbox.set_valign(Gtk.Align.CENTER)

        name_label = Gtk.Label()
        name_label.set_markup(
            f'<span size="xx-large" weight="bold">{GLib.markup_escape_text(self._primary.name)}</span>'
        )
        name_label.set_xalign(0)
        name_label.set_line_wrap(True)
        info_vbox.pack_start(name_label, False, False, 0)

        self._meta_base_parts: list[str] = [self._primary.source.capitalize(), self._primary.remote]
        if self._primary.version:
            self._meta_base_parts.append(f"v{self._primary.version}")
        self._meta_size_str: str = self._primary.download_size_str or ""
        meta_display = list(self._meta_base_parts)
        if self._meta_size_str:
            meta_display.append(self._meta_size_str)
        self._meta_label = Gtk.Label(label="  ·  ".join(meta_display))
        self._meta_label.set_xalign(0)
        self._meta_label.get_style_context().add_class("dim-label")
        info_vbox.pack_start(self._meta_label, False, False, 0)

        if self._alternates:
            source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            source_lbl = Gtk.Label(label=t(self._language, "store_detail_source"))
            source_lbl.get_style_context().add_class("dim-label")
            source_row.pack_start(source_lbl, False, False, 0)

            self._source_combo = Gtk.ComboBoxText()
            all_opts = [self._primary] + self._alternates
            for opt in all_opts:
                ver_s = f" (v{opt.version})" if opt.version else ""
                source_name = t(self._language, f"store_source_{opt.source}")
                self._source_combo.append(opt.app_id, f"{source_name} · {opt.remote}{ver_s}")
            self._source_combo.set_active(0)
            self._source_combo.connect("changed", self._on_source_changed)
            source_row.pack_start(self._source_combo, False, False, 0)
            info_vbox.pack_start(source_row, False, False, 0)

        header_box.pack_start(info_vbox, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        btn_box.set_valign(Gtk.Align.CENTER)
        self._install_btn = Gtk.Button()
        self._install_btn.get_style_context().add_class("suggested-action")
        self._update_install_btn(self._primary)
        self._install_btn.connect("clicked", self._on_install_clicked)
        btn_box.pack_start(self._install_btn, False, False, 0)

        if self._flatpak_app_id:
            flathub_url = f"https://flathub.org/apps/{self._flatpak_app_id}"
            open_btn = Gtk.LinkButton.new_with_label(flathub_url, t(self._language, "store_open_external"))
            open_btn.get_style_context().add_class("flat")
            btn_box.pack_start(open_btn, False, False, 0)

        header_box.pack_start(btn_box, False, False, 0)
        main_box.pack_start(header_box, False, False, 0)
        main_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        trust = Gtk.Label(label=t(self._language, "security_unknown"))
        trust.set_xalign(0)
        trust.get_style_context().add_class("warning-text")
        main_box.pack_start(trust, False, False, 0)
        sandbox = Gtk.Label(
            label=t(
                self._language,
                "security_flatpak" if self._primary.source == SOURCE_FLATPAK else "security_native",
            )
        )
        sandbox.set_xalign(0)
        sandbox.set_line_wrap(True)
        main_box.pack_start(sandbox, False, False, 0)
        for value in (self._primary.publisher, self._primary.license, self._primary.homepage):
            if value:
                label = Gtk.Label(label=value, xalign=0)
                label.set_line_wrap(True)
                label.set_selectable(True)
                main_box.pack_start(label, False, False, 0)

        desc_text = self._primary.description.strip()
        if desc_text:
            desc_lbl = Gtk.Label(label=desc_text)
            desc_lbl.set_xalign(0)
            desc_lbl.set_line_wrap(True)
            desc_lbl.set_selectable(True)
            main_box.pack_start(desc_lbl, False, False, 0)

        if self._flatpak_app_id:
            self._screenshots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            self._screenshots_status_label = Gtk.Label(label=t(self._language, "store_screenshots_loading"))
            self._screenshots_status_label.set_xalign(0)
            self._screenshots_status_label.get_style_context().add_class("dim-label")
            self._screenshots_box.pack_start(self._screenshots_status_label, False, False, 0)

            self._screenshots_scroll = Gtk.ScrolledWindow()
            self._screenshots_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            self._screenshots_scroll.set_min_content_height(280)
            self._screenshots_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            self._screenshots_scroll.add(self._screenshots_inner)
            self._screenshots_box.pack_start(self._screenshots_scroll, True, True, 0)
            self._screenshots_scroll.hide()
            main_box.pack_start(self._screenshots_box, True, True, 0)

        outer_scroll.add(main_box)
        content.pack_start(outer_scroll, True, True, 0)

    def _update_install_btn(self, result: StoreResult) -> None:
        is_installed = f"{result.source}:{result.app_id}" in self._installed_ids
        if is_installed:
            self._install_btn.set_label(f"✓ {t(self._language, 'store_installed_badge')}")
            self._install_btn.set_sensitive(False)
        else:
            self._install_btn.set_label(t(self._language, "store_install_btn"))
            self._install_btn.set_sensitive(True)

    def _on_source_changed(self, combo: Gtk.ComboBoxText) -> None:
        active_idx = combo.get_active()
        all_opts = [self._primary] + self._alternates
        if 0 <= active_idx < len(all_opts):
            chosen = all_opts[active_idx]
            self._selected_result = chosen
            self._load_icon(chosen, 96)
            self._update_install_btn(chosen)

            parts = [chosen.source.capitalize(), chosen.remote]
            if chosen.version:
                parts.append(f"v{chosen.version}")
            if chosen.download_size_str:
                parts.append(chosen.download_size_str)
            self._meta_label.set_text("  ·  ".join(parts))

    def _on_install_clicked(self, _btn: Gtk.Button) -> None:
        self.destroy()
        self._install_callback(self._selected_result)

    def _load_icon(self, result: StoreResult, size: int) -> None:
        if result.icon_path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(result.icon_path, size, size, True)
                self._icon_image.set_from_pixbuf(pb)
                return
            except Exception:
                pass
        theme = Gtk.IconTheme.get_default()
        for name in (result.app_id, result.name.lower(), "application-x-executable"):
            if theme.has_icon(name):
                try:
                    pb = theme.load_icon(name, size, Gtk.IconLookupFlags.GENERIC_FALLBACK)
                    self._icon_image.set_from_pixbuf(pb)
                    return
                except Exception:
                    pass
        self._icon_image.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)

    def _load_screenshots_async(self) -> None:
        if not self._flatpak_app_id:
            return
        url = f"https://flathub.org/api/v2/appstream/{self._flatpak_app_id}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SourceDock/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            GLib.idle_add(self._on_screenshots_done, [])
            return

        screenshot_urls: list[str] = []
        for s in data.get("screenshots", []):
            for sz in s.get("sizes", []):
                src = sz.get("src", "")
                if src and "624x351" in src:
                    screenshot_urls.append(src)
                    break
            else:
                for sz in s.get("sizes", []):
                    src = sz.get("src", "")
                    if src:
                        screenshot_urls.append(src)
                        break

        if not screenshot_urls:
            GLib.idle_add(self._on_screenshots_done, [])
            return

        def _worker():
            pixbufs = []
            for img_url in screenshot_urls[:4]:
                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent": "SourceDock/1.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        img_data = resp.read()
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(img_data)
                    loader.close()
                    pb = loader.get_pixbuf()
                    if pb:
                        h = 260
                        w = max(1, int(pb.get_width() * h / pb.get_height()))
                        pixbufs.append(pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR))
                except Exception:
                    pass
            GLib.idle_add(self._on_screenshots_done, pixbufs)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_screenshots_done(self, pixbufs: list) -> bool:
        if not hasattr(self, "_screenshots_status_label"):
            return False
        if not pixbufs:
            self._screenshots_status_label.set_text(t(self._language, "store_screenshots_none"))
            return False
        self._screenshots_status_label.set_text("")
        for pb in pixbufs:
            img = Gtk.Image.new_from_pixbuf(pb)
            self._screenshots_inner.pack_start(img, False, False, 0)
        self._screenshots_inner.show_all()
        self._screenshots_scroll.show()
        return False


def ask_sudo_password(
    parent: Gtk.Window,
    language: str,
    retry: bool = False,
    message_key: str = "password_placeholder",
    retry_key: str = "store_password_retry",
) -> str | None:
    """Yönetici parolasını soran modal diyalog."""
    dialog = Gtk.Dialog(
        title=t(language, "password_title"),
        transient_for=parent,
        flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
    )
    dialog.get_style_context().add_class("icon-settings-window")
    dialog.add_button(t(language, "password_cancel"), Gtk.ResponseType.CANCEL)
    ok_btn = dialog.add_button(t(language, "password_continue"), Gtk.ResponseType.OK)
    ok_btn.get_style_context().add_class("suggested-action")
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    box.set_spacing(10)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_top(16)
    box.set_margin_bottom(16)

    prompt_label = Gtk.Label(label=t(language, retry_key if retry else message_key))
    prompt_label.set_xalign(0)
    box.pack_start(prompt_label, False, False, 0)

    entry = Gtk.Entry()
    entry.set_visibility(False)
    entry.set_activates_default(True)
    box.pack_start(entry, False, False, 0)

    dialog.show_all()
    response = dialog.run()
    password = entry.get_text() if response == Gtk.ResponseType.OK else None
    dialog.destroy()
    return password


def show_snap_classic_dialog(parent: Gtk.Window, language: str, app_name: str) -> bool:
    """Snap classic confinement izni onay penceresi."""
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.NONE,
        text=t(language, "store_snap_classic_title"),
    )
    dialog.get_style_context().add_class("icon-settings-window")
    dialog.format_secondary_text(t(language, "store_snap_classic_message", name=app_name))
    dialog.add_button(t(language, "store_snap_classic_cancel"), Gtk.ResponseType.CANCEL)
    confirm_btn = dialog.add_button(t(language, "store_snap_classic_confirm"), Gtk.ResponseType.OK)
    confirm_btn.get_style_context().add_class("suggested-action")

    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK
