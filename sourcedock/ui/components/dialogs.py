#!/usr/bin/env python3
"""Yeniden kullanılabilir arayüz diyalogları (Detay, Şifre, Snap Classic vb.)."""

from __future__ import annotations

from collections.abc import Callable
import getpass
import json
import re
import threading
import urllib.request

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.models import SOURCE_FLATPAK, SOURCE_SNAP, StoreResult, is_native_source
from sourcedock.core.icons import find_flatpak_icon_path, find_snap_icon_path
from sourcedock.ui.components.common import display_store_name, prepare_dialog
from sourcedock.i18n import source_name, t


def _store_variant_identity(result: StoreResult) -> str:
    """Normalize provider variants to the same selectable app identity."""
    identity = re.sub(r"[^a-z0-9.+:-]+", "", (result.identity or "").casefold())
    package_id = re.sub(r"[^a-z0-9.+:-]+", "", (result.app_id or "").casefold())
    aliases = {
        "firefox": "org.mozilla.firefox",
    }
    return aliases.get(identity or package_id, identity or package_id)


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
            title=display_store_name(primary_result),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(self, width=720, height=380, independent=True)

        self._primary = primary_result
        self._installed_ids = installed_package_ids
        self._install_callback = install_callback
        self._language = language
        self._selected_result = primary_result
        self._source_combo: Gtk.ComboBoxText | None = None
        self._screenshots_done = False
        self._screenshot_timeout_id = 0

        primary_identity = _store_variant_identity(primary_result)
        seen_sources: set[str] = {primary_result.source}
        self._alternates: list[StoreResult] = []
        for r in all_results:
            if r.source not in seen_sources and _store_variant_identity(r) == primary_identity:
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
        # Gtk.show_all() can re-show rows hidden by _set_source_metadata().
        # Reapply visibility after the complete widget tree is realized.
        self._set_source_metadata(self._primary)

        if self._flatpak_app_id:
            self._screenshot_timeout_id = GLib.timeout_add_seconds(12, self._on_screenshot_timeout)
            threading.Thread(target=self._load_screenshots_async, daemon=True).start()

    def _build_content(self) -> None:
        content = self.get_content_area()
        content.set_spacing(0)

        outer_scroll = Gtk.ScrolledWindow()
        outer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer_scroll.set_min_content_height(0)
        outer_scroll.set_propagate_natural_height(True)

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
            f'<span size="xx-large" weight="bold">{GLib.markup_escape_text(display_store_name(self._primary))}</span>'
        )
        name_label.set_xalign(0)
        name_label.set_line_wrap(True)
        info_vbox.pack_start(name_label, False, False, 0)

        self._meta_base_parts: list[str] = [source_name(self._language, self._primary.source)]
        if self._primary.remote:
            self._meta_base_parts.append(self._primary.remote)
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
                source_label = source_name(self._language, opt.source)
                remote = f" · {opt.remote}" if opt.remote else ""
                self._source_combo.append(opt.app_id, f"{source_label}{remote}{ver_s}")
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
        self._publisher_status_label = Gtk.Label(
            label=(
                t(self._language, "security_publisher_metadata", publisher=self._primary.publisher)
                if self._primary.publisher
                else t(self._language, "security_publisher_unknown")
            )
        )
        trust = self._publisher_status_label
        trust.set_xalign(0)
        trust.get_style_context().add_class("warning-text")
        main_box.pack_start(trust, False, False, 0)
        sandbox = Gtk.Label(
            label=t(
                self._language,
                "security_flatpak"
                if self._primary.source == SOURCE_FLATPAK
                else "security_snap"
                if self._primary.source == SOURCE_SNAP
                else "security_native",
            )
        )
        self._sandbox_label = sandbox
        sandbox.set_xalign(0)
        sandbox.set_line_wrap(True)
        main_box.pack_start(sandbox, False, False, 0)
        self._sandbox_label = sandbox
        self._signature_label = Gtk.Label(
            label=t(self._language, self._signature_security_key(self._primary.source)), xalign=0
        )
        self._signature_label.set_line_wrap(True)
        self._signature_label.get_style_context().add_class("dim-label")
        main_box.pack_start(self._signature_label, False, False, 0)

        self._source_fields: dict[str, tuple[Gtk.Box, Gtk.Label]] = {}
        for field_name, label_key in (
            ("publisher", "store_detail_publisher"),
            ("license", "store_detail_license"),
            ("homepage", "store_detail_homepage"),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            caption = Gtk.Label(label=t(self._language, label_key) + ":", xalign=0)
            caption.get_style_context().add_class("dim-label")
            caption.set_size_request(110, -1)
            value = Gtk.Label(xalign=0)
            value.set_line_wrap(True)
            value.set_selectable(True)
            row.pack_start(caption, False, False, 0)
            row.pack_start(value, True, True, 0)
            main_box.pack_start(row, False, False, 0)
            self._source_fields[field_name] = (row, value)

        self._transition_label = Gtk.Label(label=t(self._language, "store_transition_warning"), xalign=0)
        self._transition_label.set_line_wrap(True)
        self._transition_label.get_style_context().add_class("warning-text")
        main_box.pack_start(self._transition_label, False, False, 0)

        desc_text = self._primary.description.strip()
        desc_lbl = Gtk.Label(label=desc_text, xalign=0)
        self._description_label = desc_lbl
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
            self._screenshots_box.set_no_show_all(True)
            self._screenshots_box.hide()
            main_box.pack_start(self._screenshots_box, True, True, 0)

        outer_scroll.add(main_box)
        content.pack_start(outer_scroll, True, True, 0)
        self._set_source_metadata(self._primary)

    def _update_install_btn(self, result: StoreResult) -> None:
        is_installed = f"{result.source}:{result.app_id}" in self._installed_ids
        if is_installed:
            self._install_btn.set_label(f"✓ {t(self._language, 'store_installed_badge')}")
            self._install_btn.set_sensitive(False)
        else:
            self._install_btn.set_label(t(self._language, "store_install_btn"))
            self._install_btn.set_sensitive(True)

    def _set_source_metadata(self, result: StoreResult) -> None:
        if hasattr(self, "_description_label"):
            self._description_label.set_text(result.description.strip())
            self._description_label.set_visible(bool(result.description.strip()))
        if hasattr(self, "_transition_label"):
            description = result.description.casefold()
            is_transition = result.source == "apt" and (
                "transitional package" in description or "snap" in description
            )
            self._transition_label.set_visible(is_transition)
        for field_name in ("publisher", "license", "homepage"):
            row, value_label = self._source_fields.get(field_name, (None, None))
            if row is None or value_label is None:
                continue
            value = getattr(result, field_name, "") or ""
            value_label.set_text(value)
            row.set_visible(bool(value.strip()))

    def _on_source_changed(self, combo: Gtk.ComboBoxText) -> None:
        active_idx = combo.get_active()
        all_opts = [self._primary] + self._alternates
        if 0 <= active_idx < len(all_opts):
            chosen = all_opts[active_idx]
            self._selected_result = chosen
            self._publisher_status_label.set_text(
                t(self._language, "security_publisher_metadata", publisher=chosen.publisher)
                if chosen.publisher
                else t(self._language, "security_publisher_unknown")
            )
            self._load_icon(chosen, 96)
            self._update_install_btn(chosen)
            self._set_source_metadata(chosen)
            if hasattr(self, "_sandbox_label"):
                self._sandbox_label.set_text(
                    t(
                        self._language,
                        "security_flatpak"
                        if chosen.source == SOURCE_FLATPAK
                        else "security_snap"
                        if chosen.source == SOURCE_SNAP
                        else "security_native",
                    )
                )
                self._signature_label.set_text(t(self._language, self._signature_security_key(chosen.source)))

            parts = [source_name(self._language, chosen.source)]
            if chosen.remote:
                parts.append(chosen.remote)
            if chosen.version:
                parts.append(f"v{chosen.version}")
            if chosen.download_size_str:
                parts.append(chosen.download_size_str)
            self._meta_label.set_text("  ·  ".join(parts))

    @staticmethod
    def _signature_security_key(source: str) -> str:
        if source == SOURCE_FLATPAK:
            return "security_signature_flatpak"
        if source == SOURCE_SNAP:
            return "security_signature_snap"
        if is_native_source(source):
            return "security_signature_native"
        return "security_signature_local"

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
        if result.source == SOURCE_FLATPAK:
            flatpak_path = find_flatpak_icon_path(result.app_id, result.remote)
            if flatpak_path:
                try:
                    self._icon_image.set_from_pixbuf(
                        GdkPixbuf.Pixbuf.new_from_file_at_scale(flatpak_path, size, size, True)
                    )
                    return
                except Exception:
                    pass
        if result.source == SOURCE_SNAP:
            snap_path = find_snap_icon_path(result.app_id)
            if snap_path:
                try:
                    self._icon_image.set_from_pixbuf(
                        GdkPixbuf.Pixbuf.new_from_file_at_scale(snap_path, size, size, True)
                    )
                    return
                except Exception:
                    pass
        theme = Gtk.IconTheme.get_default()
        generic_names = {"application-x-executable", "application-x-executable-symbolic"}
        candidates = [result.app_id] if result.app_id and result.app_id not in generic_names else []
        candidates.append("package-x-generic")
        for name in candidates:
            if theme.has_icon(name):
                try:
                    pb = theme.load_icon(name, size, Gtk.IconLookupFlags.GENERIC_FALLBACK)
                    self._icon_image.set_from_pixbuf(pb)
                    return
                except Exception:
                    pass
        self._icon_image.set_from_icon_name("package-x-generic", Gtk.IconSize.DIALOG)

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
        if not hasattr(self, "_screenshots_status_label") or self._screenshots_done:
            return False
        self._screenshots_done = True
        if self._screenshot_timeout_id:
            GLib.source_remove(self._screenshot_timeout_id)
            self._screenshot_timeout_id = 0
        if not pixbufs:
            self._screenshots_status_label.set_text(t(self._language, "store_screenshots_none"))
            self._screenshots_scroll.hide()
            self._screenshots_box.hide()
            return False
        self._screenshots_status_label.set_text("")
        for pb in pixbufs:
            img = Gtk.Image.new_from_pixbuf(pb)
            self._screenshots_inner.pack_start(img, False, False, 0)
        self._screenshots_inner.show_all()
        self._screenshots_scroll.show()
        self._screenshots_box.show()
        return False

    def _on_screenshot_timeout(self) -> bool:
        if self._screenshots_done or not hasattr(self, "_screenshots_status_label"):
            return False
        self._screenshots_done = True
        self._screenshot_timeout_id = 0
        self._screenshots_status_label.set_text(t(self._language, "store_screenshots_none"))
        self._screenshots_scroll.hide()
        self._screenshots_box.hide()
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
        modal=True,
        destroy_with_parent=True,
    )
    prepare_dialog(dialog, width=480, height=220)
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

    prompt = t(language, retry_key if retry else message_key)
    current_user = getpass.getuser()
    if current_user != "root":
        user_hint = t(language, "password_user_hint", user=current_user)
        prompt = f"{prompt}\n\n{user_hint}"
    prompt_label = Gtk.Label(label=prompt)
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
    """Show the explicit, non-default Snap Classic permission confirmation."""
    return _run_risk_confirmation(
        parent,
        title=t(language, "store_snap_classic_title"),
        body=t(language, "store_snap_classic_message", name=app_name),
        cancel_label=t(language, "store_snap_classic_cancel"),
        confirm_label=t(language, "store_snap_classic_confirm"),
        icon_name="security-high-symbolic",
    )


def show_firmware_confirmation(parent: Gtk.Window, language: str) -> bool:
    """Show a shared firmware confirmation with power and reboot guidance."""
    return _run_risk_confirmation(
        parent,
        title=t(language, "firmware_confirm_title"),
        body=t(language, "firmware_confirm_body"),
        cancel_label=t(language, "firmware_confirm_cancel"),
        confirm_label=t(language, "firmware_confirm_apply"),
        icon_name="computer-symbolic",
    )


def _run_risk_confirmation(
    parent: Gtk.Window,
    *,
    title: str,
    body: str,
    cancel_label: str,
    confirm_label: str,
    icon_name: str,
) -> bool:
    dialog = Gtk.Dialog(
        title=title,
        transient_for=parent,
        modal=True,
        destroy_with_parent=True,
    )
    prepare_dialog(dialog, width=540, height=340)
    content = dialog.get_content_area()
    content.set_spacing(0)
    content.set_margin_start(20)
    content.set_margin_end(20)
    content.set_margin_top(18)
    content.set_margin_bottom(8)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
    icon.set_pixel_size(48)
    header.pack_start(icon, False, False, 0)
    title_label = Gtk.Label(label=title, xalign=0)
    title_label.get_style_context().add_class("section-title")
    title_label.set_line_wrap(True)
    header.pack_start(title_label, True, True, 0)
    panel.pack_start(header, False, False, 0)
    panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

    for paragraph in (part.strip() for part in body.split("\n\n")):
        if not paragraph:
            continue
        label = Gtk.Label(label=paragraph, xalign=0)
        label.set_line_wrap(True)
        label.set_selectable(True)
        panel.pack_start(label, False, False, 0)
    scroll.add(panel)
    content.pack_start(scroll, True, True, 0)

    cancel_button = dialog.add_button(cancel_label, Gtk.ResponseType.CANCEL)
    confirm_button = dialog.add_button(confirm_label, Gtk.ResponseType.OK)
    confirm_button.get_style_context().add_class("destructive-action")
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    dialog.show_all()
    cancel_button.grab_focus()
    response = dialog.run()
    dialog.destroy()
    return response == Gtk.ResponseType.OK
