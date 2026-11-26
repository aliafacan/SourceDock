"""Uygulama İzinleri Yöneticisi (PermissionsDialog).

Flatpak, Snap ve yerel (APT/DNF/Pacman) paketler için sandbox
ve güvenlik izinlerini sekmeli (Notebook) ve kategorilere ayrılmış modern
bir arayüzle yöneten diyalog.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk

from sourcedock.core.errors import AuthRequiredError
from sourcedock.core.icons import find_flatpak_icon_path, find_snap_icon_path
from sourcedock.core.models import SOURCE_FLATPAK, SOURCE_SNAP
from sourcedock.i18n import t
from sourcedock.ui.components.common import prepare_dialog

if TYPE_CHECKING:
    from sourcedock.backend.models import UnifiedApplication
    from sourcedock.backend.manager import ApplicationRegistry


class PermissionsDialog(Gtk.Dialog):
    """Uygulama izinlerini sekmeli kartlar ve anahtarlarla (switch) yöneten diyalog."""

    def __init__(
        self,
        parent: Gtk.Window,
        application: UnifiedApplication,
        registry: ApplicationRegistry,
        permissions_data: dict[str, Any],
        language: str = "tr",
    ):
        super().__init__(
            title=t(language, "permissions_title").format(name=application.name),
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.application = application
        self.registry = registry
        self.language = language
        self.data = permissions_data

        prepare_dialog(self, width=850, height=500, independent=True)
        self.set_size_request(760, 440)
        self.get_style_context().add_class("permissions-dialog")
        self.add_button(t(language, "dialog_close"), Gtk.ResponseType.CLOSE)

        content_area = self.get_content_area()
        content_area.set_spacing(0)
        content_area.set_margin_start(20)
        content_area.set_margin_end(20)
        content_area.set_margin_top(16)
        content_area.set_margin_bottom(0)

        # 1. Başlık Alanı (Header)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header_box.get_style_context().add_class("permissions-heading")
        header_box.set_margin_bottom(18)
        icon_img = self._app_icon()
        header_box.pack_start(icon_img, False, False, 0)

        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title_lbl = Gtk.Label(label=application.name)
        title_lbl.get_style_context().add_class("permission-app-title")
        title_lbl.set_xalign(0)
        title_lbl.set_ellipsize(3)
        title_lbl.set_max_width_chars(36)
        meta_box.pack_start(title_lbl, False, False, 0)

        source_label = application.source.upper()
        sub_text = f"{source_label} • {application.package_name}"
        sub_lbl = Gtk.Label(label=sub_text)
        sub_lbl.get_style_context().add_class("dim-label")
        sub_lbl.set_ellipsize(3)
        sub_lbl.set_xalign(0)
        meta_box.pack_start(sub_lbl, False, False, 0)

        header_box.pack_start(meta_box, True, True, 0)

        # Sıfırla Butonu (Flatpak için)
        if application.source == SOURCE_FLATPAK:
            reset_btn = Gtk.Button(label=t(language, "flatpak_permissions_reset"))
            reset_btn.set_valign(Gtk.Align.CENTER)
            reset_btn.get_style_context().add_class("destructive-action")
            reset_btn.connect("clicked", self._on_flatpak_reset)
            header_box.pack_end(reset_btn, False, False, 0)

        content_area.pack_start(header_box, False, False, 0)

        # 2. Sekmeli Arayüz (Notebook)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(False)
        self.notebook.get_style_context().add_class("permissions-tabs")
        content_area.pack_start(self.notebook, True, True, 0)

        if application.source == SOURCE_FLATPAK:
            self._build_flatpak_tabs()
        elif application.source == SOURCE_SNAP:
            self._build_snap_tabs()
        else:
            self._build_native_tabs()

        self.show_all()

    def _app_icon(self) -> Gtk.Image:
        icon = self.application.icon or ""
        paths = [icon] if os.path.isfile(icon) else []
        if self.application.source == SOURCE_FLATPAK:
            paths.append(find_flatpak_icon_path(self.application.package_name))
        elif self.application.source == SOURCE_SNAP:
            paths.append(find_snap_icon_path(self.application.package_name))
        for path in paths:
            if path:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 56, 56, True)
                    return Gtk.Image.new_from_pixbuf(pixbuf)
                except (GLib.Error, OSError):
                    pass
        return Gtk.Image.new_from_icon_name(icon or "application-x-executable", Gtk.IconSize.DIALOG)

    def _create_tab_page(self, title: str) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
        """Sekme sayfası oluşturur: Kaydırılabilir alan içinde bir liste kutusu içerir."""
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_margin_top(4)
        scroller.set_margin_bottom(0)
        scroller.set_hexpand(True)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_start(2)
        container.set_margin_end(2)
        container.set_margin_top(14)
        container.set_margin_bottom(16)
        scroller.add(container)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon_names = {
            "📁": "folder-symbolic", "🌐": "network-workgroup-symbolic",
            "🪟": "video-display-symbolic", "⚙️": "preferences-system-symbolic",
            "🛡️": "security-high-symbolic",
        }
        prefix, _, label_text = title.partition(" ")
        icon_name = icon_names.get(prefix)
        if icon_name:
            tab_box.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
        else:
            label_text = title
        tab_label = Gtk.Label(label=label_text)
        tab_box.pack_start(tab_label, False, False, 0)
        tab_box.show_all()

        self.notebook.append_page(scroller, tab_box)
        return scroller, container

    def _info_card(self, title: str, body: str) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        card.get_style_context().add_class("permission-info")
        heading = Gtk.Label(label=title)
        heading.get_style_context().add_class("permission-section-title")
        heading.set_xalign(0)
        card.pack_start(heading, False, False, 0)
        detail = Gtk.Label(label=body)
        detail.get_style_context().add_class("dim-label")
        detail.set_xalign(0)
        detail.set_line_wrap(True)
        card.pack_start(detail, False, False, 0)
        return card

    def _create_switch_row(
        self,
        title: str,
        subtitle: str,
        is_active: bool,
        on_toggle: Callable[[bool], bool],
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.get_style_context().add_class("permission-row")

        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row_box.set_margin_top(9)
        row_box.set_margin_bottom(9)
        row_box.set_margin_start(16)
        row_box.set_margin_end(16)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        t_lbl = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>")
        t_lbl.set_use_markup(True)
        t_lbl.set_xalign(0)
        t_lbl.set_line_wrap(True)
        text_box.pack_start(t_lbl, False, False, 0)

        if subtitle:
            s_lbl = Gtk.Label(label=subtitle)
            s_lbl.get_style_context().add_class("dim-label")
            s_lbl.set_xalign(0)
            s_lbl.set_line_wrap(True)
            text_box.pack_start(s_lbl, False, False, 0)

        row_box.pack_start(text_box, True, True, 0)

        switch = Gtk.Switch()
        switch.set_active(is_active)
        switch.set_valign(Gtk.Align.CENTER)

        def _on_state_set(_sw, state):
            previous = _sw.get_state()
            if state == previous:
                return True

            # GTK moves the thumb before emitting state-set. Keep the old
            # value visible while authentication or the command is pending.
            _sw.handler_block(handler_id)
            try:
                _sw.set_active(previous)
            finally:
                _sw.handler_unblock(handler_id)

            if on_toggle(state):
                _sw.handler_block(handler_id)
                try:
                    _sw.set_active(state)
                    _sw.set_state(state)
                finally:
                    _sw.handler_unblock(handler_id)
            return True

        handler_id = switch.connect("state-set", _on_state_set)
        row_box.pack_end(switch, False, False, 0)

        row.add(row_box)
        return row

    # =========================================================================
    # FLATPAK TABS
    # =========================================================================
    def _build_flatpak_tabs(self) -> None:
        filesystems = self.data.get("filesystems", {})
        shares = self.data.get("shares", {})
        sockets = self.data.get("sockets", {})
        devices = self.data.get("devices", {})

        # Sekme 1: Dosya ve Diskler
        _, fs_container = self._create_tab_page(t(self.language, "perm_tab_filesystem"))
        fs_list = Gtk.ListBox()
        fs_list.get_style_context().add_class("permission-list")
        fs_list.set_selection_mode(Gtk.SelectionMode.NONE)
        fs_container.pack_start(fs_list, False, False, 0)

        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_home"),
            t(self.language, "perm_fs_home_desc"),
            filesystems.get("home", False),
            lambda active: self._set_flatpak_override("filesystem" if active else "nofilesystem", "home"),
        ))
        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_download"),
            t(self.language, "perm_fs_download_desc"),
            filesystems.get("xdg-download", False),
            lambda active: self._set_flatpak_override("filesystem" if active else "nofilesystem", "xdg-download"),
        ))
        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_host"),
            t(self.language, "perm_fs_host_desc"),
            filesystems.get("host", False),
            lambda active: self._set_flatpak_override("filesystem" if active else "nofilesystem", "host"),
        ))

        _, folders_container = self._create_tab_page(t(self.language, "perm_tab_folders"))
        folder_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading = Gtk.Label(label=t(self.language, "perm_folders_title"))
        heading.get_style_context().add_class("permission-section-title")
        heading.set_xalign(0)
        folder_header.pack_start(heading, True, True, 0)
        add_button = Gtk.Button(label=t(self.language, "perm_folder_add"))
        add_button.get_style_context().add_class("suggested-action")
        add_button.connect("clicked", self._add_folder)
        folder_header.pack_end(add_button, False, False, 0)
        folders_container.pack_start(folder_header, False, False, 0)
        hint = Gtk.Label(label=t(self.language, "perm_folders_hint"))
        hint.get_style_context().add_class("dim-label")
        hint.set_xalign(0)
        hint.set_line_wrap(True)
        folders_container.pack_start(hint, False, False, 0)
        self.folder_list = Gtk.ListBox()
        self.folder_list.get_style_context().add_class("permission-list")
        self.folder_list.set_selection_mode(Gtk.SelectionMode.NONE)
        folders_container.pack_start(self.folder_list, False, False, 0)
        self._render_folders()

        # Sekme 2: Ağ ve Donanım
        _, net_container = self._create_tab_page(t(self.language, "perm_tab_network"))
        net_list = Gtk.ListBox()
        net_list.get_style_context().add_class("permission-list")
        net_list.set_selection_mode(Gtk.SelectionMode.NONE)
        net_container.pack_start(net_list, False, False, 0)

        net_list.add(self._create_switch_row(
            t(self.language, "perm_net_network"),
            t(self.language, "perm_net_network_desc"),
            shares.get("network", False),
            lambda active: self._set_flatpak_override("share" if active else "unshare", "network"),
        ))
        net_list.add(self._create_switch_row(
            t(self.language, "perm_sock_sound"),
            t(self.language, "perm_sock_sound_desc"),
            sockets.get("pulseaudio", False),
            lambda active: self._set_flatpak_override("socket" if active else "nosocket", "pulseaudio"),
        ))
        net_list.add(self._create_switch_row(
            t(self.language, "perm_dev_devices"),
            t(self.language, "perm_dev_devices_desc"),
            devices.get("all", False),
            lambda active: self._set_flatpak_override("device" if active else "nodevice", "all"),
        ))

        # Sekme 3: Ekran ve Pencereleme
        _, disp_container = self._create_tab_page(t(self.language, "perm_tab_display"))
        disp_list = Gtk.ListBox()
        disp_list.get_style_context().add_class("permission-list")
        disp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        disp_container.pack_start(disp_list, False, False, 0)

        disp_list.add(self._create_switch_row(
            t(self.language, "perm_sock_wayland"),
            t(self.language, "perm_sock_wayland_desc"),
            sockets.get("wayland", False),
            lambda active: self._set_flatpak_override("socket" if active else "nosocket", "wayland"),
        ))
        disp_list.add(self._create_switch_row(
            t(self.language, "perm_sock_x11"),
            t(self.language, "perm_sock_x11_desc"),
            sockets.get("x11", False),
            lambda active: self._set_flatpak_override("socket" if active else "nosocket", "x11"),
        ))

    def _set_flatpak_override(self, override_type: str, value: str) -> bool:
        """Flatpak override uygula."""
        try:
            self.registry.set_flatpak_override(self.application.package_name, override_type, value)
            return True
        except Exception as exc:
            self._show_error(str(exc))
            return False

    def _render_folders(self) -> None:
        for child in self.folder_list.get_children():
            self.folder_list.remove(child)
        folders = self.data.get("folders", {})
        for path in sorted(path for path, allowed in folders.items() if allowed):
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.get_style_context().add_class("permission-row")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_start(14)
            box.set_margin_end(14)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            label = Gtk.Label(label=path)
            label.set_xalign(0)
            label.set_ellipsize(3)
            label.set_tooltip_text(path)
            box.pack_start(label, True, True, 0)
            remove = Gtk.Button(label=t(self.language, "perm_folder_remove"))
            remove.get_style_context().add_class("outline-danger")
            remove.connect("clicked", lambda _button, folder=path: self._remove_folder(folder))
            box.pack_end(remove, False, False, 0)
            row.add(box)
            self.folder_list.add(row)
        if not any(folders.values()):
            self.folder_list.add(self._info_card(
                t(self.language, "perm_folders_empty_title"),
                t(self.language, "perm_folders_empty_desc"),
            ))
        self.folder_list.show_all()

    def _add_folder(self, _button) -> None:
        chooser = Gtk.FileChooserDialog(
            title=t(self.language, "perm_folder_choose"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        prepare_dialog(chooser, width=780, height=540)
        chooser.get_style_context().add_class("permission-chooser")
        chooser.add_button(t(self.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(t(self.language, "perm_folder_add"), Gtk.ResponseType.OK)
        try:
            if chooser.run() != Gtk.ResponseType.OK:
                return
            path = chooser.get_filename()
        finally:
            chooser.destroy()
        if not path or self.data.get("folders", {}).get(path):
            return
        try:
            self.registry.set_flatpak_override(self.application.package_name, "filesystem", path)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.data.setdefault("folders", {})[path] = True
        self._render_folders()

    def _remove_folder(self, path: str) -> None:
        try:
            self.registry.set_flatpak_override(self.application.package_name, "nofilesystem", path)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.data.setdefault("folders", {})[path] = False
        self._render_folders()

    def _on_flatpak_reset(self, _btn) -> None:
        """Flatpak izinlerini varsayılana sıfırla."""
        try:
            self.registry.flatpak_reset_permissions(self.application.package_name)
            self.destroy()
        except Exception as exc:
            self._show_error(str(exc))

    # =========================================================================
    # SNAP TABS
    # =========================================================================
    def _build_snap_tabs(self) -> None:
        connections = self.data.get("connections", [])
        if not connections:
            _, empty_container = self._create_tab_page(t(self.language, "perm_tab_filesystem"))
            empty_container.pack_start(self._info_card(
                t(self.language, "perm_snap_folder_title"),
                t(self.language, "perm_snap_folder_hint"),
            ), False, False, 0)
            return

        # Snap bağlantılarını kategorilerine ayıralım
        # Gruplar: filesystem, network_hardware, display, other
        categories: dict[str, list[dict[str, Any]]] = {
            "filesystem": [],
            "network_hardware": [],
            "display": [],
            "other": [],
        }

        fs_interfaces = {"home", "removable-media", "system-files", "personal-files"}
        net_hw_interfaces = {
            "network", "network-bind", "network-control", "network-observe",
            "audio-playback", "audio-record", "camera", "cups-control",
            "bluetooth-control", "raw-usb", "serial-port", "hardware-observe",
        }
        disp_interfaces = {
            "x11", "wayland", "opengl", "desktop", "desktop-legacy", "unity7", "screen-inhibit-control",
        }

        for item in connections:
            iface = item["interface"]
            # İçerik/tema paylaşımlarını filtreleyelim (kullanıcı izni değildir)
            if iface.startswith("content[") or item.get("slot", "").startswith("gnome-") or item.get("slot", "").startswith("gtk-common-"):
                continue

            if iface in fs_interfaces:
                categories["filesystem"].append(item)
            elif iface in net_hw_interfaces:
                categories["network_hardware"].append(item)
            elif iface in disp_interfaces:
                categories["display"].append(item)
            else:
                categories["other"].append(item)

        tab_defs = [
            ("filesystem", t(self.language, "perm_tab_filesystem")),
            ("network_hardware", t(self.language, "perm_tab_network")),
            ("display", t(self.language, "perm_tab_display")),
            ("other", t(self.language, "perm_tab_other")),
        ]

        for cat_key, tab_title in tab_defs:
            items = categories[cat_key]
            if not items and cat_key != "filesystem":
                continue

            _, page_container = self._create_tab_page(tab_title)
            list_box = Gtk.ListBox()
            list_box.get_style_context().add_class("permission-list")
            list_box.set_selection_mode(Gtk.SelectionMode.NONE)
            page_container.pack_start(list_box, False, False, 0)

            for item in items:
                iface = item["interface"]
                is_connected = item["connected"]
                title, desc = self._get_snap_interface_meta(iface)

                def make_toggle(target_plug=item["plug"], target_slot=item["slot"]):
                    return lambda active: self._toggle_snap_connection(target_plug, target_slot, active)

                list_box.add(self._create_switch_row(
                    title,
                    desc,
                    is_connected,
                    make_toggle(),
                ))

            if cat_key == "filesystem":
                page_container.pack_start(self._info_card(
                    t(self.language, "perm_snap_folder_title"),
                    t(self.language, "perm_snap_folder_hint"),
                ), False, False, 0)


    def _get_snap_interface_meta(self, iface: str) -> tuple[str, str]:
        """Snap arayüzü için kullanıcı dostu başlık ve açıklama döndürür."""
        meta_dict = {
            "home": (
                t(self.language, "perm_snap_home_title"),
                t(self.language, "perm_snap_home_desc"),
            ),
            "removable-media": (
                t(self.language, "perm_snap_media_title"),
                t(self.language, "perm_snap_media_desc"),
            ),
            "system-files": (
                t(self.language, "perm_snap_system_files_title"),
                t(self.language, "perm_snap_system_files_desc"),
            ),
            "network": (
                t(self.language, "perm_snap_net_title"),
                t(self.language, "perm_snap_net_desc"),
            ),
            "network-bind": (
                t(self.language, "perm_snap_netbind_title"),
                t(self.language, "perm_snap_netbind_desc"),
            ),
            "audio-playback": (
                t(self.language, "perm_snap_audio_title"),
                t(self.language, "perm_snap_audio_desc"),
            ),
            "audio-record": (
                t(self.language, "perm_snap_audio_rec_title"),
                t(self.language, "perm_snap_audio_rec_desc"),
            ),
            "cups-control": (
                t(self.language, "perm_snap_cups_title"),
                t(self.language, "perm_snap_cups_desc"),
            ),
            "camera": (
                t(self.language, "perm_snap_camera_title"),
                t(self.language, "perm_snap_camera_desc"),
            ),
            "desktop": (
                t(self.language, "perm_snap_desktop_title"),
                t(self.language, "perm_snap_desktop_desc"),
            ),
            "desktop-legacy": (
                t(self.language, "perm_snap_desktop_leg_title"),
                t(self.language, "perm_snap_desktop_leg_desc"),
            ),
            "opengl": (
                t(self.language, "perm_snap_opengl_title"),
                t(self.language, "perm_snap_opengl_desc"),
            ),
            "wayland": (
                t(self.language, "perm_snap_wayland_title"),
                t(self.language, "perm_snap_wayland_desc"),
            ),
            "x11": (
                t(self.language, "perm_snap_x11_title"),
                t(self.language, "perm_snap_x11_desc"),
            ),
        }

        if iface in meta_dict:
            return meta_dict[iface]

        title = iface.replace("-", " ").capitalize()
        desc = t(self.language, "perm_snap_generic_desc", iface=iface)
        return title, desc

    def _toggle_snap_connection(self, plug: str, slot: str, connect: bool) -> bool:
        parent = self.get_transient_for()
        get_cached = getattr(parent, "get_cached_sudo_password", None)
        set_cached = getattr(parent, "set_cached_sudo_password", None)
        clear_cached = getattr(parent, "clear_cached_sudo_password", None)
        password = get_cached() if callable(get_cached) else None
        if password:
            self.registry.set_sudo_password(password)

        for attempt in range(3):
            try:
                self.registry.toggle_snap_connection(self.application.package_name, plug, connect, slot)
                if password and callable(set_cached):
                    set_cached(password)
                return True
            except AuthRequiredError as exc:
                if password and callable(clear_cached):
                    clear_cached()
                password = None
                if attempt == 2:
                    self._show_error(t(self.language, "applications_password_retry"))
                    return False
                password = self._ask_permission_password(attempt > 0 or exc.password_failed)
                if password is None:
                    self.registry.runner.clear_sudo_password()
                    return False
                self.registry.set_sudo_password(password)
            except Exception as exc:
                self._show_error(str(exc))
                return False
        return False

    def _ask_permission_password(self, retry: bool) -> str | None:
        dialog = Gtk.Dialog(
            title=t(self.language, "password_title"), transient_for=self,
            modal=True, destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=500, height=220)
        dialog.add_button(t(self.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        confirm = dialog.add_button(t(self.language, "password_continue"), Gtk.ResponseType.OK)
        confirm.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(14)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)
        box.set_margin_bottom(16)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header.pack_start(self._app_icon(), False, False, 0)
        message = Gtk.Label(label=t(
            self.language,
            "applications_password_retry" if retry else "applications_password_message",
        ))
        message.set_xalign(0)
        message.set_line_wrap(True)
        message.set_max_width_chars(44)
        header.pack_start(message, True, True, 0)
        box.pack_start(header, False, False, 0)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text(t(self.language, "password_placeholder"))
        entry.set_activates_default(True)
        box.pack_start(entry, False, False, 0)
        dialog.show_all()
        entry.grab_focus()
        result = entry.get_text() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        return result

    # =========================================================================
    # NATIVE TABS
    # =========================================================================
    def _build_native_tabs(self) -> None:
        """Yerel APT/DNF/Pacman paketleri için güvenlik ve sandbox durum sekmesi."""
        _, container = self._create_tab_page(t(self.language, "perm_tab_security"))

        card = self._info_card(
            t(self.language, "perm_native_section_title"),
            t(self.language, "perm_native_info", name=self.application.name),
        )

        # AppArmor durumu
        apparmor_active = self.data.get("apparmor_confined", False)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        aa_text = t(self.language, "perm_apparmor_active" if apparmor_active else "perm_apparmor_unconfined")
        status_box.get_style_context().add_class("permission-status")
        status_box.pack_start(Gtk.Image.new_from_icon_name(
            "security-high-symbolic" if apparmor_active else "dialog-information-symbolic",
            Gtk.IconSize.BUTTON,
        ), False, False, 0)
        aa_lbl = Gtk.Label(label=aa_text)
        aa_lbl.set_xalign(0)
        status_box.pack_start(aa_lbl, False, False, 0)
        card.pack_start(status_box, False, False, 0)

        container.pack_start(card, False, False, 0)
        container.pack_start(self._info_card(
            t(self.language, "perm_native_folder_title"),
            t(self.language, "perm_native_folder_hint"),
        ), False, False, 0)

    def _show_error(self, message: str) -> None:
        dialog = Gtk.Dialog(
            title=t(self.language, "permissions_title", name=self.application.name),
            transient_for=self, modal=True, destroy_with_parent=True,
        )
        prepare_dialog(dialog, width=480, height=180)
        dialog.add_button(t(self.language, "dialog_close"), Gtk.ResponseType.CLOSE)
        box = dialog.get_content_area()
        box.set_spacing(12)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)
        box.set_margin_bottom(16)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.pack_start(Gtk.Image.new_from_icon_name("dialog-error-symbolic", Gtk.IconSize.DIALOG), False, False, 0)
        label = Gtk.Label(label=message)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_max_width_chars(56)
        row.pack_start(label, True, True, 0)
        box.pack_start(row, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
