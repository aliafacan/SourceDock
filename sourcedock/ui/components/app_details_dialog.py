#!/usr/bin/env python3
"""Yüklü uygulama ayrıntıları ve yönetim diyaloğu (App Details Page)."""

from __future__ import annotations

from collections.abc import Callable
from configparser import ConfigParser
import os
from pathlib import Path
import threading
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.history import OperationHistory
from sourcedock.core.icons import find_flatpak_icon_path, find_snap_icon_path
from sourcedock.core.models import (
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_FIRMWARE,
    SOURCE_FLATPAK,
    SOURCE_PACMAN,
    SOURCE_PORTABLE,
    SOURCE_SNAP,
    SOURCE_ZYPPER,
    UnifiedApplication,
    is_native_source,
)
from sourcedock.i18n import source_name, t
from sourcedock.ui.components.common import ScreenshotGallery, icon_text_button, make_window_movable, prepare_dialog
from sourcedock.ui.components.removal import add_sensitive_removal_confirmation
from sourcedock.ui.components.dialogs import ask_sudo_password
from sourcedock.ui.components.progress import OperationProgressWindow
from sourcedock.store.metadata import load_metadata


def _format_size(size_kib: int | None) -> str:
    if size_kib is None or size_kib <= 0:
        return "-"
    if size_kib >= 1024 * 1024:
        return f"{size_kib / (1024 * 1024):.2f} GB"
    if size_kib >= 1024:
        return f"{size_kib / 1024:.1f} MB"
    return f"{size_kib} KB"


def _read_desktop_comment(desktop_file: str, language: str) -> str:
    if not desktop_file or not os.path.isfile(desktop_file):
        return ""
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read(desktop_file, encoding="utf-8")
        if "Desktop Entry" in parser:
            sec = parser["Desktop Entry"]
            language_base = language.split("_", 1)[0].split("-", 1)[0]
            for key in (
                f"Comment[{language}]",
                f"Comment[{language_base}]",
                "Comment[en]",
                "Comment",
                f"GenericName[{language}]",
                f"GenericName[{language_base}]",
                "GenericName[en]",
                "GenericName",
            ):
                value = sec.get(key, "").strip()
                if value:
                    return value
    except Exception:
        pass
    return ""


class InstalledAppDetailsDialog(Gtk.Dialog):
    """Yüklü bir uygulamanın tüm ayrıntılarını, meta verilerini ve işlem butonlarını sunan detay penceresi."""

    def __init__(
        self,
        application: UnifiedApplication,
        registry,
        language: str,
        parent: Gtk.Window | None = None,
        on_action_callback: Callable[[str, UnifiedApplication], None] | None = None,
        standalone: bool = False,
        removal_operation: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            title=f"{application.name} — {t(language, 'details_title')}",
            transient_for=parent,
            modal=bool(parent),
            destroy_with_parent=bool(parent),
        )
        prepare_dialog(self, width=680, height=560, independent=True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("icon-settings-window")
        self.get_style_context().add_class("package-installer-dialog")

        self.application = application
        metadata = load_metadata(language=language)
        self.metadata = metadata.get(
            Path(application.desktop_file).name, metadata.get(application.package_name, {})
        )
        if not (is_native_source(application.source) or application.source == SOURCE_FLATPAK):
            self.metadata = {}
        self.registry = registry
        self.language = language
        self.on_action_callback = on_action_callback
        self.standalone = standalone
        self._removal_operation = removal_operation
        self._action_busy = False
        self._destroyed = False
        self._cached_sudo_password: str | None = None
        self._cached_sudo_timestamp: float = 0.0

        self.connect("destroy", self._on_destroy)
        self.connect("delete-event", self._on_delete_event)

        self._build_ui()

    def _on_destroy(self, _widget) -> None:
        self._destroyed = True
        if self.standalone and not self._action_busy:
            Gtk.main_quit()

    def get_cached_sudo_password(self) -> str | None:
        parent_win = self.get_transient_for()
        if parent_win and hasattr(parent_win, "get_cached_sudo_password"):
            return parent_win.get_cached_sudo_password()
        if getattr(self, "_destroyed", False):
            self.clear_cached_sudo_password()
            return None
        pwd = getattr(self, "_cached_sudo_password", None)
        if not pwd:
            return None
        timestamp = getattr(self, "_cached_sudo_timestamp", 0.0)
        if not timestamp or time.monotonic() - timestamp > 900:
            self.clear_cached_sudo_password()
            return None
        return pwd

    def set_cached_sudo_password(self, password: str | None) -> None:
        parent_win = self.get_transient_for()
        if parent_win and hasattr(parent_win, "set_cached_sudo_password"):
            parent_win.set_cached_sudo_password(password)
            return
        self._cached_sudo_password = password
        self._cached_sudo_timestamp = time.monotonic() if password else 0.0

    def clear_cached_sudo_password(self) -> None:
        parent_win = self.get_transient_for()
        if parent_win and hasattr(parent_win, "clear_cached_sudo_password"):
            parent_win.clear_cached_sudo_password()
        self._cached_sudo_password = None
        self._cached_sudo_timestamp = 0.0
        if hasattr(self, "registry") and hasattr(self.registry, "runner"):
            self.registry.runner.clear_sudo_password()

    def _on_delete_event(self, _widget, _event) -> bool:
        if self._action_busy:
            self.iconify()
            return True
        return False

    def _build_ui(self) -> None:
        content_area = self.get_content_area()
        content_area.set_spacing(16)
        content_area.set_margin_top(20)
        content_area.set_margin_bottom(16)
        content_area.set_margin_start(20)
        content_area.set_margin_end(20)

        # 1. Başlık ve İkon Alanı
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        content_area.pack_start(header_box, False, False, 0)

        # İkon
        icon_img = Gtk.Image()
        pixbuf = self._load_app_icon(self.application, 64)
        if pixbuf:
            icon_img.set_from_pixbuf(pixbuf)
        else:
            icon_img.set_from_icon_name("package-x-generic", Gtk.IconSize.DIALOG)
        header_box.pack_start(icon_img, False, False, 0)

        # İsim, Paket Adı ve Rozetler
        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.pack_start(title_vbox, True, True, 0)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(
            f'<span size="x-large" weight="bold">{GLib.markup_escape_text(self.application.name)}</span>'
        )
        title_lbl.set_xalign(0)
        title_vbox.pack_start(title_lbl, False, False, 0)

        sub_lbl = Gtk.Label()
        sub_text = self.application.package_name or self.application.id
        sub_lbl.set_text(sub_text)
        sub_lbl.get_style_context().add_class("dim-label")
        sub_lbl.set_xalign(0)
        title_vbox.pack_start(sub_lbl, False, False, 0)

        # Rozetler (Chips)
        chips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        chips_box.set_margin_top(4)
        title_vbox.pack_start(chips_box, False, False, 0)

        # Kaynak Rozeti
        src_lbl = Gtk.Label(label=f" {self.application.source.upper()} ")
        src_lbl.get_style_context().add_class("filter-chip")
        chips_box.pack_start(src_lbl, False, False, 0)

        # Kategori Rozeti
        if self.application.category:
            cat_lbl = Gtk.Label(label=f" {self.application.category} ")
            cat_lbl.get_style_context().add_class("filter-chip")
            chips_box.pack_start(cat_lbl, False, False, 0)

        # Durum Rozeti (Güncel / Güncelleme Mevcut)
        status_lbl = Gtk.Label()
        if self.application.update_available:
            note = f" ({self.application.update_note})" if self.application.update_note else ""
            status_lbl.set_text(t(self.language, "details_status_update") + note)
            status_lbl.get_style_context().add_class("warning-text")
        else:
            status_lbl.set_text(t(self.language, "details_status_installed"))
            status_lbl.get_style_context().add_class("success-text")
        chips_box.pack_start(status_lbl, False, False, 0)

        # 2. İşlem Butonları Çubuğu (Action Bar)
        actions_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._action_bar = actions_card
        actions_card.get_style_context().add_class("action-bar")
        content_area.pack_start(actions_card, False, False, 0)

        # [Çalıştır / Launch]
        btn_launch = Gtk.Button()
        icon_text_button(
            btn_launch,
            "media-playback-start-symbolic",
            t(self.language, "details_btn_launch"),
            t(self.language, "details_btn_launch"),
        )
        btn_launch.get_style_context().add_class("suggested-action")
        btn_launch.set_sensitive(bool(self.application.executable))
        btn_launch.connect("clicked", self._on_launch_clicked)
        actions_card.pack_start(btn_launch, False, False, 0)

        # [Güncelle / Update]
        if self.application.update_available:
            btn_update = Gtk.Button()
            icon_text_button(
                btn_update,
                "software-update-available-symbolic",
                t(self.language, "details_btn_update"),
                t(self.language, "details_btn_update"),
            )
            btn_update.get_style_context().add_class("accent-action")
            btn_update.connect("clicked", self._on_update_clicked)
            actions_card.pack_start(btn_update, False, False, 0)

        # [Konum / Open Directory]
        btn_loc = Gtk.Button()
        icon_text_button(
            btn_loc,
            "folder-open-symbolic",
            t(self.language, "details_btn_location"),
            t(self.language, "details_btn_location"),
        )
        btn_loc.set_sensitive(bool(self.application.install_path or self.application.desktop_file))
        btn_loc.connect("clicked", self._on_location_clicked)
        actions_card.pack_start(btn_loc, False, False, 0)

        # [İzinler / Permissions] (Flatpak)
        if self.application.source == SOURCE_FLATPAK:
            btn_perm = Gtk.Button()
            icon_text_button(
                btn_perm,
                "changes-prevent-symbolic",
                t(self.language, "details_btn_permissions"),
                t(self.language, "details_btn_permissions"),
            )
            btn_perm.connect("clicked", self._on_permissions_clicked)
            actions_card.pack_start(btn_perm, False, False, 0)

            btn_rb = Gtk.Button()
            icon_text_button(
                btn_rb,
                "edit-undo-symbolic",
                t(self.language, "applications_rollback"),
                t(self.language, "applications_rollback"),
            )
            btn_rb.connect("clicked", self._on_rollback_clicked)
            actions_card.pack_start(btn_rb, False, False, 0)

        # [Sürüm Notları / Changelog] (Native)
        if is_native_source(self.application.source):
            btn_cl = Gtk.Button()
            icon_text_button(
                btn_cl,
                "document-open-recent-symbolic",
                t(self.language, "details_btn_changelog"),
                t(self.language, "details_btn_changelog"),
            )
            btn_cl.connect("clicked", self._on_changelog_clicked)
            actions_card.pack_start(btn_cl, False, False, 0)

        # Boşluk genişletici
        spacer = Gtk.Box()
        actions_card.pack_start(spacer, True, True, 0)

        # [Kaldır / Uninstall] (Destructive)
        if self.application.source != SOURCE_FIRMWARE:
            btn_del = Gtk.Button(label=t(self.language, "applications_remove"))
            btn_del.get_style_context().add_class("outline-danger")
            btn_del.connect("clicked", self._on_remove_clicked)
            actions_card.pack_end(btn_del, False, False, 0)

        # 3. Açıklama & Meta Veriler Alanı (Scrolled)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content_area.pack_start(scroller, True, True, 0)

        details_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        details_vbox.set_margin_start(4)
        details_vbox.set_margin_end(4)
        scroller.add(details_vbox)
        if self.metadata.get("screenshots"):
            details_vbox.pack_start(
                ScreenshotGallery(self.metadata["screenshots"], self.language), False, False, 0
            )
        publisher = self.metadata.get("publisher", "")
        trust = Gtk.Label(label=(
            t(self.language, "security_publisher_metadata", publisher=publisher)
            if publisher else t(self.language, "security_publisher_unknown")
        ))
        trust.set_xalign(0)
        trust.set_line_wrap(True)
        trust.get_style_context().add_class("dim-label" if publisher else "warning-text")
        details_vbox.pack_start(trust, False, False, 0)
        sandbox = Gtk.Label(
            label=t(
                self.language,
                "security_flatpak"
                if self.application.source == SOURCE_FLATPAK
                else "security_snap"
                if self.application.source == SOURCE_SNAP
                else "security_native",
            )
        )
        sandbox.set_xalign(0)
        sandbox.set_line_wrap(True)
        details_vbox.pack_start(sandbox, False, False, 0)
        signature_key = (
            "security_signature_flatpak"
            if self.application.source == SOURCE_FLATPAK
            else "security_signature_snap"
            if self.application.source == SOURCE_SNAP
            else "security_signature_native"
            if is_native_source(self.application.source)
            else "security_signature_local"
        )
        signature = Gtk.Label(label=t(self.language, signature_key), xalign=0)
        signature.set_line_wrap(True)
        signature.get_style_context().add_class("dim-label")
        details_vbox.pack_start(signature, False, False, 0)

        # Açıklama Kutusu
        comment = self.metadata.get("description") or _read_desktop_comment(
            self.application.desktop_file, self.language
        )
        if comment:
            desc_frame = Gtk.Frame()
            desc_frame.get_style_context().add_class("app-card")
            desc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            desc_box.set_margin_top(10)
            desc_box.set_margin_bottom(10)
            desc_box.set_margin_start(12)
            desc_box.set_margin_end(12)

            desc_title = Gtk.Label()
            desc_title.set_markup(f"<b>{t(self.language, 'details_description')}</b>")
            desc_title.set_xalign(0)
            desc_box.pack_start(desc_title, False, False, 0)

            desc_content = Gtk.Label(label=comment)
            desc_content.set_line_wrap(True)
            desc_content.set_xalign(0)
            desc_box.pack_start(desc_content, False, False, 0)

            desc_frame.add(desc_box)
            details_vbox.pack_start(desc_frame, False, False, 0)

        # Meta Veri Tablosu (Key-Value Grid)
        grid_frame = Gtk.Frame()
        grid_frame.get_style_context().add_class("app-card")
        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        grid_box.set_margin_top(12)
        grid_box.set_margin_bottom(12)
        grid_box.set_margin_start(14)
        grid_box.set_margin_end(14)

        metadata_items: list[tuple[str, str]] = [
            (t(self.language, "details_pkg_name"), self.application.package_name or self.application.id),
            (t(self.language, "details_installed_version"), self.application.version or "-"),
        ]
        if self.application.update_note:
            metadata_items.append((t(self.language, "details_new_version"), self.application.update_note))
        metadata_items.extend(
            [
                (t(self.language, "details_size"), _format_size(self.application.installed_size_kib)),
                (t(self.language, "details_source"), source_name(self.language, self.application.source)),
                (t(self.language, "details_install_date"), self.application.installed_date or "-"),
                (t(self.language, "details_last_updated"), self.application.last_updated or "-"),
                (t(self.language, "details_executable"), self.application.executable or "-"),
                (t(self.language, "details_install_path"), self.application.install_path or "-"),
                (t(self.language, "details_desktop_file"), self.application.desktop_file or "-"),
            ]
        )
        for key, field in (
            ("details_publisher", "publisher"),
            ("details_license", "license"),
            ("details_homepage", "homepage"),
        ):
            value = self.metadata.get(field)
            if value:
                metadata_items.append((t(self.language, key), value))

        for label_text, val_text in metadata_items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            lbl = Gtk.Label()
            lbl.set_text(label_text + ":")
            lbl.get_style_context().add_class("dim-label")
            lbl.set_xalign(0)
            lbl.set_line_wrap(True)
            lbl.set_size_request(180, -1)
            row.pack_start(lbl, False, False, 0)

            val = Gtk.Label(label=val_text)
            val.set_xalign(0)
            val.set_line_wrap(True)
            val.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            val.set_selectable(True)
            row.pack_start(val, True, True, 0)
            grid_box.pack_start(row, False, False, 0)

        grid_frame.add(grid_box)
        details_vbox.pack_start(grid_frame, False, False, 0)

        # 4. Alt Kapat Butonu
        btn_close = Gtk.Button(label=t(self.language, "dialog_close"))
        btn_close.set_size_request(100, -1)
        btn_close.connect("clicked", lambda _: self.destroy())
        self.get_action_area().pack_end(btn_close, False, False, 0)

        self.show_all()

    def _load_app_icon(self, app: UnifiedApplication, size: int = 64) -> GdkPixbuf.Pixbuf | None:
        icon_name = app.icon
        if icon_name and os.path.exists(icon_name):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_name, size, size, True)
                return pb
            except Exception:
                pass
        if app.source == SOURCE_FLATPAK:
            flatpak_path = find_flatpak_icon_path(app.package_name or app.id)
            if flatpak_path:
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(flatpak_path, size, size, True)
                except Exception:
                    pass
        if app.source == SOURCE_SNAP:
            snap_path = find_snap_icon_path(app.package_name or app.id)
            if snap_path:
                try:
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(snap_path, size, size, True)
                except Exception:
                    pass
        theme = Gtk.IconTheme.get_default()
        generic_names = {"application-x-executable", "application-x-executable-symbolic"}
        candidates = [icon_name] if icon_name and icon_name not in generic_names else []
        candidates.append("package-x-generic")
        for name in candidates:
            if name and theme.has_icon(name):
                try:
                    return theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                except Exception:
                    pass
        return None

    def _on_launch_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("launch", self.application)
        else:
            try:
                self.registry.launch(self.application)
            except BackendError as exc:
                self._show_error(str(exc))

    def _on_update_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("update", self.application)
            self.destroy()
        else:
            self._run_standalone_action("update", lambda: self.registry.update(self.application))

    def _run_standalone_action(self, action: str, operation: Callable[[], None]) -> None:
        if self._action_busy or self._destroyed:
            return
        self._action_busy = True
        self._action_bar.set_sensitive(False)
        op_id = f"op_detail_{id(self)}_{int(time.monotonic() * 1000)}"
        cancel_action = (
            (lambda: self.registry.cancel_current(target=op_id))
            if hasattr(self.registry, "cancel_current")
            else (lambda: self.registry.runner.cancel_current(target=op_id))
        )
        progress = OperationProgressWindow(
            title=t(self.language, f"details_btn_{action}"),
            message=self.application.name,
            parent=self,
            language=self.language,
            cancel_fn=cancel_action,
        )

        def get_auth_pwd():
            return self.get_cached_sudo_password()

        def set_auth_pwd(pwd):
            self.set_cached_sudo_password(pwd)

        def clear_auth_pwd():
            self.clear_cached_sudo_password()

        cached = get_auth_pwd()
        if cached:
            self.registry.set_sudo_password(cached)

        def finish(error):
            if not self._action_busy:
                return False
            if isinstance(error, AuthRequiredError) and not self._destroyed:
                if error.password_failed:
                    clear_auth_pwd()
                cached_now = get_auth_pwd()
                if cached_now and not error.password_failed:
                    self.registry.set_sudo_password(cached_now)
                    start_worker()
                    return False
                password = ask_sudo_password(
                    self, self.language, retry=error.password_failed,
                    message_key="applications_password_message", retry_key="applications_password_retry",
                )
                if password is not None:
                    set_auth_pwd(password)
                    self.registry.set_sudo_password(password)
                    start_worker()
                    return False
                clear_auth_pwd()
                message = t(self.language, "status_cancelled")
            elif error is not None:
                message = str(error)
            else:
                message = t(self.language, f"applications_{action}_done")
            self._action_busy = False
            success = error is None
            try:
                OperationHistory().append(
                    f"{action}: {self.application.package_name or self.application.id}",
                    self.application.source, success, message,
                )
            except OSError as exc:
                progress.append_log(str(exc))
            progress.finish(success, message)
            if self._destroyed:
                if self.standalone:
                    progress.connect("destroy", lambda _widget: Gtk.main_quit())
            else:
                self._action_bar.set_sensitive(True)
                if success:
                    self.destroy()
            return False

        def worker():
            error = None
            if hasattr(self.registry, "bind_thread_op"):
                self.registry.bind_thread_op(op_id)
            elif hasattr(self.registry.runner, "bind_thread_op"):
                self.registry.runner.bind_thread_op(op_id)
            should_finish_now = True
            try:
                operation()
            except Exception as exc:
                orig_exc = exc
                runner = getattr(self.registry, "runner", None)
                ctx = runner.get_operation_context(op_id) if runner and hasattr(runner, "get_operation_context") else None
                if ctx and getattr(ctx, "lingering", False) is True:
                    def _log_lingering():
                        progress.append_log("İşlem arka planda güvenle tamamlanması bekleniyor...")
                        return False
                    GLib.idle_add(_log_lingering)
                    wait_timeout = getattr(runner, "_lingering_wait_timeout", 1800)
                    completed = ctx.completed_event.wait(timeout=wait_timeout)
                    if completed:
                        if ctx.returncode == 0:
                            error = None
                        else:
                            error = orig_exc
                    else:
                        should_finish_now = False
                        def _log_still_running():
                            progress.append_log("İşlem arka planda güvenle devam ediyor...")
                            return False
                        GLib.idle_add(_log_still_running)

                        def _watch_lingering():
                            ctx.completed_event.wait()
                            self.registry.runner.set_output_callback(None, op_id=op_id)
                            self.registry.runner.clear_sudo_password()
                            final_err = None if ctx.returncode == 0 else orig_exc
                            GLib.idle_add(lambda: (finish(final_err), False)[1])

                        threading.Thread(target=_watch_lingering, daemon=True, name=f"watch-{op_id}").start()
                else:
                    error = orig_exc
            finally:
                if hasattr(self.registry, "unbind_thread_op"):
                    self.registry.unbind_thread_op(op_id)
                elif hasattr(self.registry.runner, "unbind_thread_op"):
                    self.registry.runner.unbind_thread_op(op_id)
                if should_finish_now:
                    self.registry.runner.set_output_callback(None, op_id=op_id)
                    self.registry.runner.clear_sudo_password()
            if should_finish_now:
                GLib.idle_add(lambda: (finish(error), False)[1])

        def start_worker():
            cached_now = get_auth_pwd()
            if cached_now and not getattr(self.registry.runner, "_sudo_password", None):
                self.registry.set_sudo_password(cached_now)
            self.registry.runner.set_output_callback(
                lambda line: GLib.idle_add(progress.append_log, line),
                op_id=op_id,
            )
            self._action_thread = threading.Thread(target=worker, name="sourcedock-detail-action", daemon=True)
            self._action_thread.start()

        start_worker()

    def _on_location_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("location", self.application)
        else:
            try:
                self.registry.open_location(self.application)
            except BackendError as exc:
                self._show_error(str(exc))

    def _on_permissions_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("permissions", self.application)

    def _on_rollback_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("rollback", self.application)

    def _on_changelog_clicked(self, _btn) -> None:
        if self.on_action_callback:
            self.on_action_callback("changelog", self.application)

    def _on_remove_clicked(self, _btn) -> None:
        if self._action_busy:
            return
        if self.on_action_callback:
            self.on_action_callback("remove", self.application)
            return
        # Doğrudan kaldırma onayı
        dialog = Gtk.Dialog(
            title=t(self.language, "details_remove_confirm_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        make_window_movable(dialog)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(18)
        content.set_margin_end(18)
        content.set_margin_top(16)
        content.set_margin_bottom(8)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.pack_start(
            Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.DIALOG), False, False, 0
        )
        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{t(self.language, 'details_remove_confirm_title')}</b>")
        title_label.set_xalign(0)
        header.pack_start(title_label, True, True, 0)
        content.pack_start(header, False, False, 0)
        body = Gtk.Label(label=t(self.language, "details_remove_confirm_text", name=self.application.name))
        body.set_xalign(0)
        body.set_line_wrap(True)
        content.pack_start(body, False, False, 0)
        dialog.add_button(t(self.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = dialog.add_button(t(self.language, "details_btn_remove"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")
        add_sensitive_removal_confirmation(content, del_btn, [self.application], self.language)

        purge_check = Gtk.CheckButton(label=t(self.language, "details_remove_purge_check"))
        purge_check.set_no_show_all(self._removal_operation is not None)
        purge_check.set_margin_start(12)
        purge_check.set_margin_top(8)
        content.pack_start(purge_check, False, False, 0)
        dialog.show_all()

        resp = dialog.run()
        is_purge = purge_check.get_active()
        dialog.destroy()

        if resp == Gtk.ResponseType.OK:
            operation = self._removal_operation or (lambda: self.registry.remove(self.application, purge=is_purge))
            self._run_standalone_action("remove", operation)

    def _show_error(self, message: str) -> None:
        err = Gtk.MessageDialog(
            transient_for=self,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.NONE,
            text=message,
        )
        err.add_button(t(self.language, "dialog_close"), Gtk.ResponseType.CLOSE)
        err.run()
        err.destroy()
