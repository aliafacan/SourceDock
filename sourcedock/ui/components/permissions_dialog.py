"""Uygulama İzinleri Yöneticisi (PermissionsDialog).

Flatpak, Snap ve yerel (APT/DNF/Pacman) paketler için sandbox
ve güvenlik izinlerini yöneten modern, interaktif diyalog.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from sourcedock.core.models import SOURCE_FLATPAK, SOURCE_SNAP, is_native_source
from sourcedock.i18n import t
from sourcedock.ui.components.common import prepare_dialog

if TYPE_CHECKING:
    from sourcedock.backend.models import UnifiedApplication
    from sourcedock.backend.manager import ApplicationRegistry


class PermissionsDialog(Gtk.Dialog):
    """Uygulama izinlerini görsel anahtarlarla (switch) yöneten diyalog."""

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

        prepare_dialog(self, width=540, height=480)
        self.add_button(t(language, "dialog_close"), Gtk.ResponseType.CLOSE)

        box = self.get_content_area()
        box.set_spacing(10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        # Header: Icon / App Name / Source Badge
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        icon_img = Gtk.Image.new_from_icon_name(application.icon or "application-x-executable", Gtk.IconSize.DIALOG)
        header_box.pack_start(icon_img, False, False, 0)

        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_lbl = Gtk.Label(label=f"<b>{GLib.markup_escape_text(application.name)}</b>")
        title_lbl.set_use_markup(True)
        title_lbl.set_xalign(0)
        meta_box.pack_start(title_lbl, False, False, 0)

        source_label = application.source.upper()
        sub_text = f"{source_label} • {application.package_name}"
        sub_lbl = Gtk.Label(label=sub_text)
        sub_lbl.get_style_context().add_class("dim-label")
        sub_lbl.set_xalign(0)
        meta_box.pack_start(sub_lbl, False, False, 0)

        header_box.pack_start(meta_box, True, True, 0)

        # Sıfırla Butonu (Flatpak için)
        if application.source == SOURCE_FLATPAK:
            reset_btn = Gtk.Button(label=t(language, "flatpak_permissions_reset"))
            reset_btn.set_valign(Gtk.Align.CENTER)
            reset_btn.connect("clicked", self._on_flatpak_reset)
            header_box.pack_end(reset_btn, False, False, 0)

        box.pack_start(header_box, False, False, 0)

        # Ayırıcı
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(sep, False, False, 0)

        # İçerik Alanı (ScrolledWindow)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        items_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        scroller.add(items_container)

        if application.source == SOURCE_FLATPAK:
            self._build_flatpak_ui(items_container)
        elif application.source == SOURCE_SNAP:
            self._build_snap_ui(items_container)
        else:
            self._build_native_ui(items_container)

        self.show_all()

    def _create_switch_row(
        self,
        title: str,
        subtitle: str,
        is_active: bool,
        on_toggle: Callable[[bool], None],
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_box.set_margin_top(8)
        row_box.set_margin_bottom(8)
        row_box.set_margin_start(10)
        row_box.set_margin_end(10)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t_lbl = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>")
        t_lbl.set_use_markup(True)
        t_lbl.set_xalign(0)
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
            on_toggle(state)
            return False

        switch.connect("state-set", _on_state_set)
        row_box.pack_end(switch, False, False, 0)

        row.add(row_box)
        return row

    def _build_flatpak_ui(self, container: Gtk.Box) -> None:
        """Flatpak izin kategorileri."""
        # 1. Dosya Sistemi
        fs_frame = Gtk.Frame(label=f" 📁 {t(self.language, 'perm_cat_filesystem')} ")
        fs_list = Gtk.ListBox()
        fs_list.set_selection_mode(Gtk.SelectionMode.NONE)
        fs_frame.add(fs_list)

        filesystems = self.data.get("filesystems", {})
        # home
        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_home"),
            t(self.language, "perm_fs_home_desc"),
            filesystems.get("home", False),
            lambda active: self._set_flatpak_override("filesystem", "home" if active else "!home"),
        ))
        # host (tüm sistem)
        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_host"),
            t(self.language, "perm_fs_host_desc"),
            filesystems.get("host", False),
            lambda active: self._set_flatpak_override("filesystem", "host" if active else "!host"),
        ))
        # xdg-download
        fs_list.add(self._create_switch_row(
            t(self.language, "perm_fs_download"),
            t(self.language, "perm_fs_download_desc"),
            filesystems.get("xdg-download", False) or filesystems.get("home", False) or filesystems.get("host", False),
            lambda active: self._set_flatpak_override("filesystem", "xdg-download" if active else "!xdg-download"),
        ))
        container.pack_start(fs_frame, False, False, 0)

        # 2. Ağ & Donanım
        net_frame = Gtk.Frame(label=f" 🌐 {t(self.language, 'perm_cat_network_hardware')} ")
        net_list = Gtk.ListBox()
        net_list.set_selection_mode(Gtk.SelectionMode.NONE)
        net_frame.add(net_list)

        shares = self.data.get("shares", {})
        sockets = self.data.get("sockets", {})
        devices = self.data.get("devices", {})

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
        container.pack_start(net_frame, False, False, 0)

        # 3. Ekran & Pencereleme
        win_frame = Gtk.Frame(label=f" 🪟 {t(self.language, 'perm_cat_display')} ")
        win_list = Gtk.ListBox()
        win_list.set_selection_mode(Gtk.SelectionMode.NONE)
        win_frame.add(win_list)

        win_list.add(self._create_switch_row(
            t(self.language, "perm_sock_x11"),
            t(self.language, "perm_sock_x11_desc"),
            sockets.get("x11", False),
            lambda active: self._set_flatpak_override("socket" if active else "nosocket", "x11"),
        ))
        win_list.add(self._create_switch_row(
            t(self.language, "perm_sock_wayland"),
            t(self.language, "perm_sock_wayland_desc"),
            sockets.get("wayland", False),
            lambda active: self._set_flatpak_override("socket" if active else "nosocket", "wayland"),
        ))
        container.pack_start(win_frame, False, False, 0)

    def _set_flatpak_override(self, override_type: str, value: str) -> None:
        """Flatpak override uygula."""
        try:
            self.registry.set_flatpak_override(self.application.package_name, override_type, value)
        except Exception as exc:
            self._show_error(str(exc))

    def _on_flatpak_reset(self, _btn) -> None:
        """Flatpak izinlerini varsayılana sıfırla."""
        try:
            self.registry.flatpak_reset_permissions(self.application.package_name)
            # Pencereyi kapatıp yeniden yüklemesi için kullanıcıya bilgi ver
            self.destroy()
        except Exception as exc:
            self._show_error(str(exc))

    def _build_snap_ui(self, container: Gtk.Box) -> None:
        """Snap arayüzleri ve bağlantıları."""
        frame = Gtk.Frame(label=f" ⚡ {t(self.language, 'perm_cat_snap_plugs')} ")
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        frame.add(list_box)

        connections = self.data.get("connections", [])
        if not connections:
            empty_lbl = Gtk.Label(label=t(self.language, "permissions_none"))
            empty_lbl.set_margin_top(16)
            empty_lbl.set_margin_bottom(16)
            list_box.add(empty_lbl)
        else:
            for item in connections:
                iface = item["interface"]
                is_connected = item["connected"]
                desc = self._snap_interface_desc(iface)

                def make_toggle(target_iface=iface):
                    return lambda active: self._toggle_snap_connection(target_iface, active)

                list_box.add(self._create_switch_row(
                    iface,
                    desc,
                    is_connected,
                    make_toggle(),
                ))

        container.pack_start(frame, False, False, 0)

    def _toggle_snap_connection(self, interface: str, connect: bool) -> None:
        try:
            self.registry.toggle_snap_connection(self.application.package_name, interface, connect)
        except Exception as exc:
            self._show_error(str(exc))

    def _build_native_ui(self, container: Gtk.Box) -> None:
        """Yerel APT/DNF/Pacman paketleri için güvenlik ve sandbox bilgisi."""
        frame = Gtk.Frame(label=f" 🛡️ {t(self.language, 'perm_cat_system_security')} ")
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        frame.add(vbox)

        info_lbl = Gtk.Label(label=t(self.language, "perm_native_info", name=self.application.name))
        info_lbl.set_line_wrap(True)
        info_lbl.set_xalign(0)
        vbox.pack_start(info_lbl, False, False, 0)

        # AppArmor durumu
        apparmor_active = self.data.get("apparmor_confined", False)
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        badge = "🟢" if apparmor_active else "⚪"
        aa_text = t(self.language, "perm_apparmor_active" if apparmor_active else "perm_apparmor_unconfined")
        aa_lbl = Gtk.Label(label=f"{badge} {aa_text}")
        aa_lbl.set_xalign(0)
        status_box.pack_start(aa_lbl, False, False, 0)
        vbox.pack_start(status_box, False, False, 0)

        container.pack_start(frame, False, False, 0)

    def _snap_interface_desc(self, iface: str) -> str:
        descs = {
            "home": t(self.language, "perm_snap_home_desc"),
            "removable-media": t(self.language, "perm_snap_media_desc"),
            "network": t(self.language, "perm_net_network_desc"),
            "audio-playback": t(self.language, "perm_sock_sound_desc"),
            "cups-control": t(self.language, "perm_snap_cups_desc"),
            "camera": t(self.language, "perm_snap_camera_desc"),
            "desktop": t(self.language, "perm_snap_desktop_desc"),
            "x11": t(self.language, "perm_sock_x11_desc"),
            "wayland": t(self.language, "perm_sock_wayland_desc"),
            "opengl": t(self.language, "perm_snap_opengl_desc"),
        }
        return descs.get(iface, t(self.language, "perm_snap_generic_desc", iface=iface))

    def _show_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()
