#!/usr/bin/env python3
"""Yerel paket önizleme ve kurulum diyaloğu (PackageInstallerDialog)."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.models import InstalledPackageStatus, LocalPackageInfo
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.local_packages import launch_local_package
from sourcedock.backend.mime_integration import get_icon_path
from sourcedock.i18n import t, translate_backend_message
from sourcedock.ui.components.common import make_window_movable, prepare_dialog, set_status
from sourcedock.backend.previews import preview_install_plan


class PackageInstallerDialog(Gtk.Dialog):
    """Yerel bir paketin (.deb, .AppImage, arşiv, vb.) metaverilerini gösterip kurulum onayını alan ve kurulumu yürüten pencere."""

    def __init__(
        self,
        parent: Gtk.Window | None = None,
        info: LocalPackageInfo | None = None,
        language: str = "tr",
        is_installed: bool = False,
        pkg_status: InstalledPackageStatus | None = None,
        registry: ApplicationRegistry | None = None,
        standalone: bool = False,
        on_finished: Callable[[], None] | None = None,
    ):
        super().__init__(
            title=t(language, "package_installer_title"),
            transient_for=parent,
            modal=bool(parent),
            destroy_with_parent=bool(parent),
        )
        self.info = info or LocalPackageInfo(file_path="", format="deb", name="")
        self.language = language
        self.registry = registry or ApplicationRegistry()
        self.standalone = standalone
        self.on_finished = on_finished

        self.pkg_status = pkg_status or InstalledPackageStatus(
            is_installed=is_installed,
            status="same_version" if is_installed else "not_installed",
        )
        self.is_installed = self.pkg_status.is_installed
        self.is_reinstall = self.pkg_status.status == "same_version"

        prepare_dialog(self, width=520, height=460, independent=True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")

        # Pencere ikonu
        icon_file = get_icon_path()
        if os.path.exists(icon_file):
            try:
                self.set_icon_from_file(icon_file)
            except Exception:
                pass

        self._pulse_timeout_id: int | None = None
        self._is_installing = False
        self._current_op_id: str | None = None

        self.create_desktop_check: Gtk.CheckButton | None = None
        self.copy_to_apps_check: Gtk.CheckButton | None = None
        self.delete_after_check: Gtk.CheckButton | None = None
        self.flatpak_scope_user_radio: Gtk.RadioButton | None = None
        self.flatpak_scope_system_radio: Gtk.RadioButton | None = None

        self._build_ui()
        self.connect("destroy", self._on_window_destroyed)
        self.connect("delete-event", lambda _window, _event: self._is_installing)

    def _build_ui(self) -> None:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        viewport.set_max_content_height(540)
        viewport.set_propagate_natural_height(True)
        viewport.add(content)
        self.get_content_area().pack_start(viewport, True, True, 0)
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
        title_lbl.set_markup(
            f'<span size="x-large" weight="bold">{GLib.markup_escape_text(self.info.name)}</span>'
        )
        title_lbl.set_xalign(0)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_badge_box.pack_start(title_lbl, False, False, 0)

        badge_lbl = Gtk.Label()
        badge_text = self._format_badge()
        badge_lbl.set_text(f"  {badge_text}  ")
        badge_lbl.get_style_context().add_class("package-badge")
        badge_lbl.set_valign(Gtk.Align.CENTER)
        name_badge_box.pack_start(badge_lbl, False, False, 0)

        status = self.pkg_status.status
        if status == "same_version":
            inst_badge = Gtk.Label()
            inst_badge.set_text(f"  ✓ {t(self.language, 'package_installer_already_installed_badge')}  ")
            inst_badge.get_style_context().add_class("package-status-success")
            inst_badge.set_valign(Gtk.Align.CENTER)
            name_badge_box.pack_start(inst_badge, False, False, 0)
        elif status == "upgradable":
            inst_badge = Gtk.Label()
            inst_badge.set_text(f"  ↑ {t(self.language, 'package_installer_update_badge')}  ")
            inst_badge.get_style_context().add_class("package-status-warning")
            inst_badge.set_valign(Gtk.Align.CENTER)
            name_badge_box.pack_start(inst_badge, False, False, 0)
        elif status == "downgrade":
            inst_badge = Gtk.Label()
            inst_badge.set_text(f"  ↓ {t(self.language, 'package_installer_downgrade_badge')}  ")
            inst_badge.get_style_context().add_class("package-status-danger")
            inst_badge.set_valign(Gtk.Align.CENTER)
            name_badge_box.pack_start(inst_badge, False, False, 0)

        # Sürüm Bilgisi Satırı
        if status == "upgradable" and self.pkg_status.installed_version:
            ver_lbl = Gtk.Label()
            ver_lbl.set_text(f"v{self.pkg_status.installed_version} → v{self.info.version}")
            ver_lbl.get_style_context().add_class("package-version-change")
            ver_lbl.set_xalign(0)
            title_vbox.pack_start(ver_lbl, False, False, 0)
        elif status == "downgrade" and self.pkg_status.installed_version:
            ver_lbl = Gtk.Label()
            ver_lbl.set_text(f"v{self.pkg_status.installed_version} → v{self.info.version}")
            ver_lbl.get_style_context().add_class("package-version-change")
            ver_lbl.get_style_context().add_class("downgrade")
            ver_lbl.set_xalign(0)
            title_vbox.pack_start(ver_lbl, False, False, 0)
        elif self.info.version:
            ver_lbl = Gtk.Label()
            ver_lbl.set_text(f"v{self.info.version}")
            ver_lbl.get_style_context().add_class("dim-label")
            ver_lbl.set_xalign(0)
            title_vbox.pack_start(ver_lbl, False, False, 0)

        if self.info.summary:
            summary_lbl = Gtk.Label(label=self.info.summary)
            summary_lbl.set_line_wrap(True)
            summary_lbl.set_xalign(0)
            summary_lbl.get_style_context().add_class("dim-label")
            title_vbox.pack_start(summary_lbl, False, False, 0)

        # Bilgilendirme / İpucu Kutusu
        if status == "upgradable":
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_lbl = Gtk.Label()
            hint_msg = t(
                self.language,
                "package_installer_update_hint",
                installed_version=self.pkg_status.installed_version,
                new_version=self.info.version,
            )
            hint_lbl.set_text(f"ℹ {hint_msg}")
            hint_lbl.get_style_context().add_class("package-version-change")
            hint_lbl.set_line_wrap(True)
            hint_lbl.set_xalign(0)
            hint_box.pack_start(hint_lbl, True, True, 0)
            content.pack_start(hint_box, False, False, 0)
        elif status == "downgrade":
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_lbl = Gtk.Label()
            hint_msg = t(
                self.language,
                "package_installer_downgrade_hint",
                installed_version=self.pkg_status.installed_version,
            )
            hint_lbl.set_text(f"⚠ {hint_msg}")
            hint_lbl.get_style_context().add_class("warning-text")
            hint_lbl.set_line_wrap(True)
            hint_lbl.set_xalign(0)
            hint_box.pack_start(hint_lbl, True, True, 0)
            content.pack_start(hint_box, False, False, 0)
        elif status == "same_version":
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_lbl = Gtk.Label()
            hint_lbl.set_text(f"ℹ {t(self.language, 'package_installer_already_installed_hint')}")
            hint_lbl.get_style_context().add_class("success-text")
            hint_lbl.set_line_wrap(True)
            hint_lbl.set_xalign(0)
            hint_box.pack_start(hint_lbl, True, True, 0)
            content.pack_start(hint_box, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        # 2. Önizleme ve Seçenekler Alanı (Kurulum başlayınca gizlenecek)
        self.preview_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.pack_start(self.preview_container, True, True, 0)

        # Detay Bilgileri Tablosu
        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(16)
        self.grid.set_row_spacing(6)
        self.preview_container.pack_start(self.grid, False, False, 0)

        row = 0
        file_size_str = self._format_file_size(self.info.size_bytes)
        row = self._add_grid_row(self.grid, row, t(self.language, "packages_col_size") + ":", file_size_str)

        if self.info.installed_size:
            row = self._add_grid_row(
                self.grid,
                row,
                t(self.language, "package_installer_installed_size") + ":",
                self.info.installed_size,
            )

        if self.info.architecture:
            row = self._add_grid_row(
                self.grid, row, t(self.language, "package_installer_arch") + ":", self.info.architecture
            )

        if self.info.maintainer:
            row = self._add_grid_row(
                self.grid, row, t(self.language, "package_installer_maintainer") + ":", self.info.maintainer
            )

        if self.info.file_path:
            row = self._add_grid_row(
                self.grid,
                row,
                t(self.language, "package_installer_file") + ":",
                Path(self.info.file_path).name,
            )
            row = self._add_grid_row(
                self.grid, row, t(self.language, "package_installer_file_path") + ":", self.info.file_path
            )
        row = self._add_grid_row(
            self.grid,
            row,
            t(self.language, "security_privileges") + ":",
            t(self.language, "security_privilege_admin")
            if self.info.format in ("deb", "rpm")
            else t(self.language, "security_privilege_user"),
        )
        security = Gtk.Label(
            label=t(
                self.language,
                "security_appimage_body" if self.info.format == "appimage" else "security_local_body",
            )
        )
        security.set_line_wrap(True)
        security.set_max_width_chars(58)
        security.set_xalign(0)
        security.get_style_context().add_class("warning-text")
        self.preview_container.pack_start(security, False, False, 0)
        if self.info.dependencies:
            dependency_text = Gtk.Label(label=", ".join(self.info.dependencies), xalign=0)
            dependency_text.set_line_wrap(True)
            dependency_text.set_max_width_chars(58)
            self.preview_container.pack_start(dependency_text, False, False, 0)
        if self.info.format in ("deb", "rpm"):
            self.plan_button = Gtk.Button(label=t(self.language, "package_plan"))
            self.plan_button.connect("clicked", self._on_preview_plan)
            self.preview_container.pack_start(self.plan_button, False, False, 0)

        if self.info.description:
            desc_scroll = Gtk.ScrolledWindow()
            desc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            desc_scroll.set_min_content_height(70)
            desc_scroll.set_max_content_height(100)
            desc_lbl = Gtk.Label(label=self.info.description)
            desc_lbl.set_line_wrap(True)
            desc_lbl.set_xalign(0)
            desc_lbl.get_style_context().add_class("dim-label")
            desc_scroll.add(desc_lbl)
            self.preview_container.pack_start(desc_scroll, False, False, 0)

        # Kurulum Seçenekleri
        self.options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.preview_container.pack_start(self.options_box, False, False, 0)

        if self.info.format in ("appimage", "archive"):
            self.create_desktop_check = Gtk.CheckButton(
                label=t(self.language, "package_installer_create_shortcut")
            )
            self.create_desktop_check.set_tooltip_text(t(self.language, "tooltip_installer_create_shortcut"))
            self.create_desktop_check.set_active(True)
            self.options_box.pack_start(self.create_desktop_check, False, False, 0)

        if self.info.format == "appimage":
            self.copy_to_apps_check = Gtk.CheckButton(label=t(self.language, "package_installer_copy_apps"))
            self.copy_to_apps_check.set_tooltip_text(t(self.language, "tooltip_installer_copy_apps"))
            self.copy_to_apps_check.set_active(True)
            self.options_box.pack_start(self.copy_to_apps_check, False, False, 0)

        if self.info.format in ("deb", "rpm", "flatpak", "flatpakref", "archive"):
            self.delete_after_check = Gtk.CheckButton(
                label=t(self.language, "package_installer_delete_after")
            )
            self.delete_after_check.set_tooltip_text(t(self.language, "tooltip_installer_delete_after"))
            self.delete_after_check.set_active(False)
            self.options_box.pack_start(self.delete_after_check, False, False, 0)

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
            self.options_box.pack_start(scope_box, False, False, 0)

        # 3. İlerleme Alanı (Kurulum sırasında görünür)
        self.progress_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.progress_container.set_no_show_all(True)
        content.pack_start(self.progress_container, True, True, 0)

        self.progress_status_label = Gtk.Label(label=t(self.language, "progress_preparing"))
        self.progress_status_label.set_xalign(0)
        self.progress_container.pack_start(self.progress_status_label, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        self.progress_container.pack_start(self.progress_bar, False, False, 0)

        # Detaylar / Log Expander
        self.log_expander = Gtk.Expander(label=t(self.language, "package_installer_details"))
        self.log_expander.set_expanded(False)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_min_content_height(110)
        log_scroll.set_max_content_height(160)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buffer = self.log_view.get_buffer()
        log_scroll.add(self.log_view)
        self.log_expander.add(log_scroll)
        self.progress_container.pack_start(self.log_expander, True, True, 0)

        # 4. Sonuç Alanı (Başarı veya Hata)
        self.result_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.result_container.set_no_show_all(True)
        content.pack_start(self.result_container, False, False, 0)

        self.result_badge_label = Gtk.Label()
        self.result_badge_label.set_xalign(0)
        self.result_container.pack_start(self.result_badge_label, False, False, 0)

        self.result_detail_label = Gtk.Label()
        self.result_detail_label.set_xalign(0)
        self.result_detail_label.set_line_wrap(True)
        self.result_detail_label.get_style_context().add_class("dim-label")
        self.result_container.pack_start(self.result_detail_label, False, False, 0)

        # 5. Alt Butonlar Alanı
        action_area = self.get_action_area()
        for child in action_area.get_children():
            action_area.remove(child)

        self.cancel_btn = Gtk.Button(label=t(self.language, "password_cancel"))
        self.cancel_btn.set_tooltip_text(t(self.language, "tooltip_installer_cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel_clicked)
        action_area.pack_start(self.cancel_btn, False, False, 0)

        if self.pkg_status.status == "upgradable":
            action_label = t(self.language, "package_installer_update_btn")
        elif self.pkg_status.status == "downgrade":
            action_label = t(self.language, "package_installer_downgrade_btn")
        elif self.pkg_status.status == "same_version":
            action_label = t(self.language, "package_installer_reinstall_btn")
        else:
            action_label = t(self.language, "package_installer_install_btn")

        self.action_btn = Gtk.Button(label=action_label)
        self.action_btn.get_style_context().add_class("suggested-action")
        self.action_btn.set_tooltip_text(t(self.language, "tooltip_installer_install"))
        self.action_btn.connect("clicked", self._on_start_install_clicked)
        action_area.pack_start(self.action_btn, False, False, 0)

        # Başarı & Hata Butonları
        self.launch_btn = Gtk.Button(label=t(self.language, "package_installer_launch_btn"))
        self.launch_btn.get_style_context().add_class("suggested-action")
        self.launch_btn.set_tooltip_text(t(self.language, "tooltip_installer_launch"))
        self.launch_btn.connect("clicked", self._on_launch_clicked)
        self.launch_btn.set_no_show_all(True)
        action_area.pack_start(self.launch_btn, False, False, 0)

        self.retry_btn = Gtk.Button(label=t(self.language, "package_installer_retry_btn"))
        self.retry_btn.get_style_context().add_class("suggested-action")
        self.retry_btn.set_tooltip_text(t(self.language, "tooltip_installer_retry"))
        self.retry_btn.connect("clicked", self._on_retry_clicked)
        self.retry_btn.set_no_show_all(True)
        action_area.pack_start(self.retry_btn, False, False, 0)

        self.close_btn = Gtk.Button(label=t(self.language, "package_installer_close_btn"))
        self.close_btn.set_tooltip_text(t(self.language, "tooltip_installer_close"))
        self.close_btn.connect("clicked", self._on_close_clicked)
        self.close_btn.set_no_show_all(True)
        action_area.pack_start(self.close_btn, False, False, 0)
        self.trust_check = Gtk.CheckButton(label=t(self.language, "security_trust_confirmation"))
        self.trust_check.connect("toggled", lambda button: self.action_btn.set_sensitive(button.get_active()))
        self.options_box.pack_start(self.trust_check, False, False, 0)
        self.action_btn.set_sensitive(False)

    def _start_installation(self) -> None:
        """Kurulum sürecini pencere içinde başlatır."""
        if not self.trust_check.get_active() or self._is_installing:
            return
        self._is_installing = True
        self._current_op_id = f"op_pkg_{id(self)}_{int(time.monotonic() * 1000)}"

        # UI durumunu güncelle
        self.preview_container.hide()
        self.action_btn.hide()
        self.retry_btn.hide()
        self.result_container.hide()
        self.launch_btn.hide()
        self.close_btn.hide()

        self.cancel_btn.show()
        self.cancel_btn.set_sensitive(True)
        if self.info.format in ("deb", "rpm", "archive", "appimage") or self.flatpak_scope == "--system":
            self.cancel_btn.set_sensitive(False)
            self.cancel_btn.set_tooltip_text(t(self.language, "cancel_critical"))

        self.progress_status_label.set_text(t(self.language, "progress_preparing"))
        self.progress_bar.set_fraction(0.0)
        self.log_buffer.set_text("")
        self.progress_container.set_no_show_all(False)
        self.progress_container.show_all()

        # Pulse timer başlat
        self._stop_pulse()
        self._pulse_timeout_id = GLib.timeout_add(100, self._on_pulse_tick)

        # Kurulum parametrelerini al
        target_dir = os.path.expanduser("~/Applications") if self.should_copy_to_applications else None
        create_desktop = self.should_create_desktop
        scope = self.flatpak_scope
        reinstall = self.should_reinstall
        delete_after = self.should_delete_installer

        # Runner çıktı dinleyicisini izole işlem kimliğiyle bağla (P1-01)
        self.registry.runner.set_output_callback(
            lambda line: GLib.idle_add(self._append_log, line),
            op_id=self._current_op_id,
        )

        threading.Thread(
            target=self._worker_install,
            args=(target_dir, create_desktop, scope, reinstall, delete_after),
            daemon=True,
        ).start()

    def _worker_install(
        self,
        target_dir: str | None,
        create_desktop: bool,
        scope: str,
        reinstall: bool,
        delete_after: bool,
    ) -> None:
        deleted = False

        def _cleanup_file_if_requested() -> bool:
            if delete_after and os.path.exists(self.info.file_path):
                try:
                    os.remove(self.info.file_path)
                    return True
                except OSError:
                    return False
            return False

        if self._current_op_id:
            self.registry.runner.bind_thread_op(self._current_op_id)
        try:
            self.registry.install_local_package(
                info=self.info,
                target_dir=target_dir,
                create_desktop=create_desktop,
                scope=scope,
                reinstall=reinstall,
            )

            deleted = _cleanup_file_if_requested()
            self.registry.runner.set_output_callback(None, op_id=self._current_op_id)
            GLib.idle_add(lambda: (self._on_install_success(deleted), False)[1])

        except AuthRequiredError as auth_err:
            pwd_failed = auth_err.password_failed
            self.registry.runner.set_output_callback(None, op_id=self._current_op_id)
            GLib.idle_add(lambda: (self._prompt_auth_and_retry(pwd_failed), False)[1])
        except Exception as exc:
            err_msg = str(exc)
            runner = getattr(self.registry, "runner", None)
            ctx = runner.get_operation_context(self._current_op_id) if runner and hasattr(runner, "get_operation_context") else None
            if ctx and getattr(ctx, "lingering", False) is True:
                def _log_pkg_lingering():
                    self.progress_status_label.set_text("İşlem arka planda güvenle tamamlanması bekleniyor...")
                    return False
                GLib.idle_add(_log_pkg_lingering)

                def _finalize_pkg(retcode: int | None):
                    self.registry.runner.set_output_callback(None, op_id=self._current_op_id)
                    if retcode == 0:
                        del_ok = _cleanup_file_if_requested()
                        GLib.idle_add(lambda: (self._on_install_success(del_ok), False)[1])
                    else:
                        fail_msg = f"{err_msg} (Kod {retcode})"
                        GLib.idle_add(lambda: (self._on_install_failure(fail_msg), False)[1])

                wait_timeout = getattr(runner, "_lingering_wait_timeout", 1800)
                completed = ctx.completed_event.wait(timeout=wait_timeout)
                if completed:
                    _finalize_pkg(ctx.returncode)
                    return
                else:
                    def _log_pkg_still_running():
                        self.progress_status_label.set_text(
                            "İşlem arka planda güvenle çalışmaya devam ediyor..."
                        )
                        return False
                    GLib.idle_add(_log_pkg_still_running)

                    def _watch_pkg():
                        ctx.completed_event.wait()
                        _finalize_pkg(ctx.returncode)
                    threading.Thread(target=_watch_pkg, daemon=True, name=f"watch-pkg-{self._current_op_id}").start()
                    return

            self.registry.runner.set_output_callback(None, op_id=self._current_op_id)
            GLib.idle_add(lambda: (self._on_install_failure(err_msg), False)[1])
        finally:
            if self._current_op_id:
                self.registry.runner.unbind_thread_op(self._current_op_id)
            self.registry.runner.clear_sudo_password()

    def _on_install_success(self, deleted_file: bool) -> None:
        self._is_installing = False
        self._stop_pulse()
        self.progress_bar.set_fraction(1.0)
        self.progress_status_label.set_text(t(self.language, "progress_done"))

        self.result_badge_label.set_text(f"✓ {t(self.language, 'package_installer_install_success')}")
        self.result_badge_label.get_style_context().add_class("success-text")
        if deleted_file:
            self.result_detail_label.set_text(t(self.language, "package_installer_deleted_notice"))
            self.result_detail_label.show()
        else:
            self.result_detail_label.hide()

        self.result_container.set_no_show_all(False)
        self.result_container.show_all()
        if not deleted_file:
            self.result_detail_label.hide()
        self.cancel_btn.hide()
        can_launch = self.info.format in ("appimage", "archive", "flatpak", "flatpakref")
        if self.info.format in ("deb", "rpm"):
            can_launch = bool(self.info.exec_path or self.registry.runner.command_exists(self.info.name))
        self.launch_btn.set_visible(can_launch)
        self.close_btn.show()

        if self.on_finished is not None:
            try:
                self.on_finished()
            except Exception:
                pass

    def _on_install_failure(self, error_msg: str) -> None:
        self._is_installing = False
        self._stop_pulse()
        self.progress_bar.set_fraction(0.0)
        self.progress_status_label.set_text(t(self.language, "progress_failed"))

        clean_err = translate_backend_message(self.language, error_msg)
        self.result_badge_label.set_text(f"✗ {t(self.language, 'package_installer_install_failed')}")
        self.result_badge_label.get_style_context().add_class("error-text")
        self.result_detail_label.set_text(clean_err)
        self.result_detail_label.show()

        self.result_container.set_no_show_all(False)
        self.result_container.show_all()
        self.log_expander.set_expanded(True)

        self.cancel_btn.hide()
        self.retry_btn.show()
        self.close_btn.show()

    def _prompt_auth_and_retry(self, failed: bool = False) -> None:
        """Yönetici parolası gerektiğinde modal parola penceresi açar ve kurulumu tekrarlar."""
        self._stop_pulse()
        self.progress_status_label.set_text(t(self.language, "progress_auth_needed"))
        self.log_expander.set_expanded(True)
        self.present()
        dialog = Gtk.Dialog(
            title=t(self.language, "password_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        make_window_movable(dialog)
        dialog.get_style_context().add_class("icon-settings-window")
        dialog.add_button(t(self.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(self.language, "password_continue"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(14)
        content.set_margin_bottom(14)

        msg = t(self.language, "applications_password_retry" if failed else "applications_password_message")
        msg = f"{msg}\n\n{t(self.language, 'password_operation', operation=self.info.name)}"
        lbl = Gtk.Label(label=msg)
        lbl.set_line_wrap(True)
        lbl.set_xalign(0)
        content.pack_start(lbl, False, False, 0)

        pwd_entry = Gtk.Entry()
        pwd_entry.set_visibility(False)
        pwd_entry.set_placeholder_text(t(self.language, "password_placeholder"))
        pwd_entry.connect("activate", lambda _: dialog.response(Gtk.ResponseType.OK))
        content.pack_start(pwd_entry, False, False, 0)

        dialog.show_all()
        dialog.present()
        resp = dialog.run()
        pwd = pwd_entry.get_text()
        dialog.destroy()

        if resp == Gtk.ResponseType.OK and pwd:
            self.registry.runner.set_sudo_password(pwd)
            # The failed attempt is already over. Clear the guard before
            # starting a new worker; otherwise _start_installation() treats
            # the retry as the still-running original attempt and returns.
            self._is_installing = False
            self._start_installation()
        else:
            self._on_install_failure(t(self.language, "progress_auth_needed"))

    def _append_log(self, line: str) -> None:
        """Terminal çıktısını textview ve durum etiketine yazar."""
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, line + "\n")
        self.log_view.scroll_to_iter(self.log_buffer.get_end_iter(), 0.0, False, 0.0, 0.0)

        trimmed = line.strip()
        if trimmed:
            normalized = trimmed.casefold()
            if "password is required" in normalized or "parola gerekiyor" in normalized:
                self.progress_status_label.set_text(t(self.language, "progress_auth_needed"))
            elif len(trimmed) < 80:
                self.progress_status_label.set_text(trimmed)

    def _on_pulse_tick(self) -> bool:
        if self._is_installing:
            self.progress_bar.pulse()
            return True
        return False

    def _stop_pulse(self) -> None:
        if self._pulse_timeout_id is not None:
            GLib.source_remove(self._pulse_timeout_id)
            self._pulse_timeout_id = None

    def _on_start_install_clicked(self, _btn: Gtk.Button) -> None:
        self._start_installation()

    def _on_preview_plan(self, button):
        button.set_sensitive(False)

        def worker():
            try:
                text = preview_install_plan(self.registry.runner, self.info)
            except Exception as exc:
                text = str(exc)
            GLib.idle_add(self._show_preview_plan, text)

        threading.Thread(target=worker, daemon=True).start()

    def _show_preview_plan(self, text):
        if getattr(self, "_destroyed", False):
            return False
        self.plan_button.set_sensitive(True)
        dialog = Gtk.Dialog(
            title=t(self.language, "package_plan"), transient_for=self, modal=True, destroy_with_parent=True
        )
        dialog.set_default_size(620, 400)
        make_window_movable(dialog)
        dialog.add_button(t(self.language, "dialog_close"), Gtk.ResponseType.CLOSE)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(text)
        scroller = Gtk.ScrolledWindow()
        scroller.add(view)
        dialog.get_content_area().pack_start(scroller, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
        return False

    def _on_retry_clicked(self, _btn: Gtk.Button) -> None:
        self.result_container.hide()
        self.result_container.set_no_show_all(True)
        self._start_installation()

    def _on_launch_clicked(self, _btn: Gtk.Button) -> None:
        """Yeni kurulan uygulamayı başlatır ve pencereyi kapatır."""
        try:
            self.registry.launch_local_package(self.info)
        except Exception:
            pass
        self._close_window()

    def _on_cancel_clicked(self, _btn: Gtk.Button) -> None:
        if self._is_installing:
            cancelled = (
                self.registry.runner.cancel_current(target=self._current_op_id)
                if self._current_op_id
                else self.registry.runner.cancel_current()
            )
            if not cancelled:
                self.progress_status_label.set_text(t(self.language, "cancel_critical"))
            self.cancel_btn.set_sensitive(False)
        else:
            self._close_window()

    def _on_close_clicked(self, _btn: Gtk.Button) -> None:
        self._close_window()

    def _close_window(self) -> None:
        self._stop_pulse()
        self.destroy()

    def _on_window_destroyed(self, _widget) -> None:
        self._destroyed = True
        self._stop_pulse()
        if self.standalone:
            Gtk.main_quit()

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

    def _format_badge(self) -> str:
        badges = {
            "deb": "DEB",
            "appimage": "AppImage",
            "archive": "PORTABLE",
            "flatpakref": "Flatpak",
            "flatpak": "Flatpak",
            "rpm": "RPM",
        }
        return badges.get(self.info.format, self.info.format.upper())

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
        val.set_hexpand(True)
        val.set_max_width_chars(36)
        val.set_tooltip_text(value_text)
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
