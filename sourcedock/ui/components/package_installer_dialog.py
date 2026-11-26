#!/usr/bin/env python3
"""Yerel paket önizleme ve kurulum diyaloğu (PackageInstallerDialog)."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
import textwrap
from typing import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.models import InstalledPackageStatus, LocalPackageInfo, UnifiedApplication
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.local_packages import launch_local_package
from sourcedock.backend.mime_integration import get_icon_path
from sourcedock.i18n import t, translate_backend_message
from sourcedock.preferences import PreferencesStore
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
        replacement_application: UnifiedApplication | None = None,
    ):
        super().__init__(
            title=t(language, "package_installer_title"),
            transient_for=parent,
            modal=bool(parent),
            destroy_with_parent=bool(parent),
        )
        self.info = info or LocalPackageInfo(file_path="", format="deb", name="")
        self.language = language
        self.preferences = PreferencesStore().load()
        self.registry = registry or ApplicationRegistry()
        self.standalone = standalone
        self.on_finished = on_finished
        self.replacement_application = replacement_application

        self.pkg_status = pkg_status or InstalledPackageStatus(
            is_installed=is_installed,
            status="same_version" if is_installed else "not_installed",
        )
        self.is_installed = self.pkg_status.is_installed
        self.is_reinstall = self.pkg_status.status == "same_version"

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        if display and parent and parent.get_window():
            monitor = display.get_monitor_at_window(parent.get_window()) or monitor
        if display and monitor is None:
            monitor = display.get_monitor(0)
        workarea = monitor.get_workarea() if monitor else None
        width = min(680, max(320, workarea.width - 48)) if workarea else 680
        height = min(620, max(260, workarea.height - 40)) if workarea else 570
        prepare_dialog(self, width=width, height=height, independent=True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")
        self.get_style_context().add_class("local-installer-dialog")

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
        self.replace_native_check: Gtk.CheckButton | None = None
        self.flatpak_scope_user_radio: Gtk.RadioButton | None = None
        self.flatpak_scope_system_radio: Gtk.RadioButton | None = None

        self._build_ui()
        self.connect("destroy", self._on_window_destroyed)
        self.connect("delete-event", lambda _window, _event: self._is_installing)

    def _build_ui(self) -> None:
        content_area = self.get_content_area()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        viewport = Gtk.ScrolledWindow()
        viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        viewport.set_min_content_height(120)
        viewport.add(content)
        self.overview_scroller = viewport
        details_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details_content.set_margin_top(8)
        details_content.set_margin_bottom(8)
        details_content.set_margin_start(14)
        details_content.set_margin_end(14)
        details_viewport = Gtk.ScrolledWindow()
        details_viewport.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        details_viewport.add(details_content)
        self.details_scroller = details_viewport
        self.preview_stack = Gtk.Stack()
        self.preview_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.preview_stack.add_titled(viewport, "overview", t(self.language, "package_installer_overview"))
        self.preview_stack.add_titled(details_viewport, "details", t(self.language, "package_installer_details"))
        self.preview_switcher = Gtk.StackSwitcher()
        self.preview_switcher.set_stack(self.preview_stack)
        self.preview_switcher.set_halign(Gtk.Align.START)
        self.preview_switcher.get_style_context().add_class("installer-tabs")
        content.set_spacing(5)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        content.set_margin_start(14)
        content.set_margin_end(14)

        # 1. Başlık ve İkon Alanı
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header_box.get_style_context().add_class("installer-heading")
        content_area.pack_start(header_box, False, False, 0)
        content_area.pack_start(self.preview_switcher, False, False, 0)
        content_area.pack_start(self.preview_stack, True, True, 0)

        icon_widget = self._create_icon_widget()
        icon_frame = Gtk.Box()
        icon_frame.get_style_context().add_class("installer-icon-frame")
        icon_frame.add(icon_widget)
        header_box.pack_start(icon_frame, False, False, 0)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.pack_start(title_vbox, True, True, 0)

        # Başlık ve Format Rozeti
        name_badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_vbox.pack_start(name_badge_box, False, False, 0)

        title_lbl = Gtk.Label()
        title_lbl.set_markup(
            f'<span size="large" weight="bold">{GLib.markup_escape_text(self.info.name)}</span>'
        )
        title_lbl.set_xalign(0)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        name_badge_box.pack_start(title_lbl, True, True, 0)

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
            content.pack_start(summary_lbl, False, False, 0)
        if self.info.description:
            short_description = textwrap.shorten(
                self.info.description, width=125, placeholder="…"
            )
            if short_description and short_description != self.info.summary:
                description_lbl = Gtk.Label(label=short_description, xalign=0)
                description_lbl.set_line_wrap(True)
                description_lbl.get_style_context().add_class("installer-overview-description")
                content.pack_start(description_lbl, False, False, 0)

        # Bilgilendirme / İpucu Kutusu
        hint_msg = None
        hint_icon = "emblem-default-symbolic"
        hint_style = "success-text"
        if status == "upgradable":
            hint_msg = t(
                self.language,
                "package_installer_update_hint",
                installed_version=self.pkg_status.installed_version,
                new_version=self.info.version,
            )
        elif status == "downgrade":
            hint_msg = t(
                self.language,
                "package_installer_downgrade_hint",
                installed_version=self.pkg_status.installed_version,
            )
            hint_icon = "dialog-warning-symbolic"
            hint_style = "warning-text"
        elif status == "same_version":
            hint_msg = t(self.language, "package_installer_already_installed_hint")
        if hint_msg:
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_box.get_style_context().add_class("installer-status-note")
            if status == "downgrade":
                hint_box.get_style_context().add_class("caution")
            hint_image = Gtk.Image.new_from_icon_name(hint_icon, Gtk.IconSize.BUTTON)
            hint_image.set_valign(Gtk.Align.START)
            hint_image.get_style_context().add_class(hint_style)
            hint_box.pack_start(hint_image, False, False, 0)
            hint_lbl = Gtk.Label(label=hint_msg)
            hint_lbl.get_style_context().add_class(hint_style)
            hint_lbl.set_line_wrap(True)
            hint_lbl.set_xalign(0)
            hint_box.pack_start(hint_lbl, True, True, 0)
            content.pack_start(hint_box, False, False, 0)

        # 2. Önizleme ve Seçenekler Alanı (Kurulum başlayınca gizlenecek)
        self.preview_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.preview_container.get_style_context().add_class("installer-preview-card")
        content.pack_start(self.preview_container, True, True, 0)

        facts = Gtk.Grid(column_spacing=8, row_spacing=8)
        facts.get_style_context().add_class("installer-facts")
        self.preview_container.pack_start(facts, False, False, 0)
        for index, (label, value) in enumerate((
            (t(self.language, "package_installer_file"), Path(self.info.file_path).name or self.info.name),
            (t(self.language, "packages_col_size"), self._format_file_size(self.info.size_bytes)),
            (t(self.language, "security_privileges"),
             t(self.language, "security_privilege_admin") if self.info.format in ("deb", "rpm")
             else t(self.language, "security_privilege_user")),
        )):
            fact = self._make_info_cell(label, value, wrap=True)
            fact.get_style_context().add_class("installer-fact")
            facts.attach(fact, 0 if index != 2 else 1, 0 if index == 0 else 1, 2 if index == 0 else 1, 1)

        self.metadata_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.metadata_card.get_style_context().add_class("installer-details-card")
        details_content.pack_start(self.metadata_card, False, False, 0)
        metadata = [
            ("package_installer_installed_size", self.info.installed_size),
            ("package_installer_arch", self.info.architecture),
            ("package_installer_maintainer", self.info.maintainer),
            ("package_installer_file_path", self.info.file_path),
        ]
        metadata = [(label, value) for label, value in metadata if value]
        for label, value in metadata[:2]:
            self.metadata_card.pack_start(
                self._make_detail_row(t(self.language, label), value), False, False, 0
            )

        if self.info.dependencies:
            dependencies_text = "\n".join(self.info.dependencies)
            dependencies_title = f"{t(self.language, 'package_installer_deps')} · {len(self.info.dependencies)}"
            if len(self.info.dependencies) > 5:
                dependency_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                dependency_section.get_style_context().add_class("installer-dependency-section")
                self.dependencies_button = Gtk.Button()
                self.dependencies_button.set_relief(Gtk.ReliefStyle.NONE)
                self.dependencies_button.get_style_context().add_class("installer-dependency-toggle")
                button_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                self.dependencies_icon = Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.MENU)
                button_content.pack_start(self.dependencies_icon, False, False, 0)
                button_content.pack_start(Gtk.Label(label=dependencies_title, xalign=0), True, True, 0)
                self.dependencies_button.add(button_content)
                self.dependencies_button.connect("clicked", self._toggle_dependencies)
                dependency_section.pack_start(self.dependencies_button, False, False, 0)
                self.dependencies_revealer = Gtk.Revealer()
                self.dependencies_revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
                dependency_label = Gtk.Label(label=dependencies_text, xalign=0)
                dependency_label.set_selectable(True)
                dependency_label.set_line_wrap(True)
                dependency_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                dependency_label.set_margin_top(8)
                dependency_label.set_margin_start(22)
                self.dependencies_revealer.add(dependency_label)
                dependency_section.pack_start(self.dependencies_revealer, False, False, 0)
                self.metadata_card.pack_start(dependency_section, False, False, 0)
            else:
                self.metadata_card.pack_start(
                    self._make_detail_row(dependencies_title, dependencies_text), False, False, 0,
                )

        for label, value in metadata[2:]:
            self.metadata_card.pack_start(
                self._make_detail_row(t(self.language, label), value), False, False, 0
            )

        if self.info.description:
            self.metadata_card.pack_start(
                self._make_detail_row(t(self.language, "details_description"), self.info.description),
                False, False, 0,
            )
        security = Gtk.Label(label=t(self.language, "security_local_short"))
        security.set_tooltip_text(t(
            self.language, "security_appimage_body" if self.info.format == "appimage" else "security_local_body"
        ))
        security.set_line_wrap(True)
        security.set_max_width_chars(58)
        security.set_xalign(0)
        security.get_style_context().add_class("warning-text")
        security.get_style_context().add_class("installer-security-note")
        self.preview_container.pack_start(security, False, False, 0)
        if self.info.format in ("deb", "rpm"):
            self.plan_button = Gtk.Button(label=t(self.language, "package_plan_short"))
            self.plan_button.set_tooltip_text(t(self.language, "package_plan"))
            self.plan_button.connect("clicked", self._on_preview_plan)
            self.plan_button.get_style_context().add_class("installer-secondary-action")

        # Kurulum Seçenekleri
        self.options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.options_box.get_style_context().add_class("installer-options-card")
        content_area.pack_start(self.options_box, False, False, 0)

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
            scope_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            scope_lbl = Gtk.Label(label=t(self.language, "package_installer_scope_title") + ":")
            scope_lbl.set_xalign(0)
            scope_lbl.get_style_context().add_class("dim-label")
            scope_box.pack_start(scope_lbl, False, False, 0)

            self.flatpak_scope_user_radio = Gtk.RadioButton.new_with_label(
                None, t(self.language, "cleanup_scope_user")
            )
            self.flatpak_scope_system_radio = Gtk.RadioButton.new_with_label_from_widget(
                self.flatpak_scope_user_radio, t(self.language, "cleanup_scope_system")
            )
            self.flatpak_scope_user_radio.set_tooltip_text(t(self.language, "package_installer_scope_user"))
            self.flatpak_scope_system_radio.set_tooltip_text(t(self.language, "package_installer_scope_system"))
            self.flatpak_scope_user_radio.set_active(True)
            scope_box.pack_start(self.flatpak_scope_user_radio, False, False, 0)
            scope_box.pack_start(self.flatpak_scope_system_radio, False, False, 0)
            self.options_box.pack_start(scope_box, False, False, 0)

        if self.replacement_application is not None:
            self.replace_native_check = Gtk.CheckButton(
                label=t(
                    self.language,
                    "package_installer_replace_native",
                    name=self.replacement_application.name,
                    version=self.replacement_application.version,
                )
            )
            self.replace_native_check.set_tooltip_text(
                t(self.language, "tooltip_installer_replace_native")
            )
            self.options_box.pack_start(self.replace_native_check, False, False, 0)

        # 3. İlerleme Alanı (Kurulum sırasında görünür)
        self.progress_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.progress_container.get_style_context().add_class("installer-progress-card")
        self.progress_container.set_no_show_all(True)
        content_area.pack_start(self.progress_container, True, True, 0)

        self.progress_status_label = Gtk.Label(label=t(self.language, "progress_preparing"))
        self.progress_status_label.set_xalign(0)
        self.progress_container.pack_start(self.progress_status_label, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        self.progress_container.pack_start(self.progress_bar, False, False, 0)

        # Detaylar / Log Expander
        self.log_expander = Gtk.Expander(label=t(self.language, "package_installer_details"))
        self.log_expander.set_expanded(
            getattr(self.preferences, "show_operation_details_by_default", False)
        )
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
        self.result_container.get_style_context().add_class("installer-result-card")
        self.result_container.set_no_show_all(True)
        content_area.pack_start(self.result_container, False, False, 0)

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
        action_area.get_style_context().add_class("installer-actions")
        for child in action_area.get_children():
            action_area.remove(child)
        if self.info.format in ("deb", "rpm"):
            action_area.pack_start(self.plan_button, False, False, 0)

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
        self.trust_check.get_style_context().add_class("installer-trust")
        self.trust_check.connect("toggled", lambda button: self.action_btn.set_sensitive(button.get_active()))
        self.options_box.pack_start(self.trust_check, False, False, 0)
        self.action_btn.set_sensitive(False)

    def _start_installation(self) -> None:
        """Kurulum sürecini pencere içinde başlatır."""
        if not self.trust_check.get_active() or self._is_installing:
            return
        self._is_installing = True
        self.set_modal(False)
        self._current_op_id = f"op_pkg_{id(self)}_{int(time.monotonic() * 1000)}"

        # UI durumunu güncelle
        for attr in ("preview_stack", "preview_switcher", "options_box"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.hide()
        if self.info.format in ("deb", "rpm") and getattr(self, "plan_button", None) is not None:
            self.plan_button.hide()
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
                    runner = self.registry.runner
                    if not runner.command_exists("gio"):
                        return False
                    runner.run(["gio", "trash", self.info.file_path], timeout=10, check=True)
                    return not os.path.exists(self.info.file_path)
                except (BackendError, OSError):
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

            if self.should_replace_native and self.replacement_application is not None:
                self.registry.remove(self.replacement_application)

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
        if line.startswith("SOURCEDOCK_PHASE "):
            self.progress_status_label.set_text(t(
                self.language, {"queued": "progress_queued", "authorizing": "progress_authorizing"}.get(line.split()[1], "progress_running")
            ))
            return
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

    def _make_info_cell(self, label_text: str, value_text: str, *, wrap: bool = False) -> Gtk.Box:
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cell.set_hexpand(True)
        label = Gtk.Label(label=label_text, xalign=0)
        label.set_width_chars(1)
        label.set_max_width_chars(16)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_tooltip_text(label_text)
        label.get_style_context().add_class("installer-fact-label")
        cell.pack_start(label, False, False, 0)
        value = Gtk.Label(label=value_text, xalign=0)
        value.set_hexpand(True)
        value.set_width_chars(1)
        if wrap:
            value.set_line_wrap(True)
            value.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        else:
            value.set_max_width_chars(28)
            value.set_ellipsize(Pango.EllipsizeMode.END)
        value.set_tooltip_text(value_text)
        value.get_style_context().add_class("installer-fact-value")
        cell.pack_start(value, False, False, 0)
        return cell

    def _make_detail_row(self, label_text: str, value_text: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        row.get_style_context().add_class("installer-detail-row")
        label = Gtk.Label(label=label_text, xalign=0)
        label.get_style_context().add_class("installer-fact-label")
        row.pack_start(label, False, False, 0)
        value = Gtk.Label(label=value_text, xalign=0)
        value.set_selectable(True)
        value.set_line_wrap(True)
        value.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        value.get_style_context().add_class("installer-fact-value")
        row.pack_start(value, False, False, 0)
        return row

    def _toggle_dependencies(self, _button: Gtk.Button) -> None:
        expanded = not self.dependencies_revealer.get_reveal_child()
        self.dependencies_revealer.set_reveal_child(expanded)
        self.dependencies_icon.set_from_icon_name(
            "go-down-symbolic" if expanded else "go-next-symbolic", Gtk.IconSize.MENU
        )

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

    @property
    def should_replace_native(self) -> bool:
        return self.replace_native_check.get_active() if self.replace_native_check else False
