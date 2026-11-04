"""Shared explicit confirmation for removal of sensitive native packages."""

from gi.repository import Gtk

from sourcedock.core.models import SOURCE_FLATPAK, SOURCE_SNAP, is_native_source


def is_system_component(app):
    """Shared runtimes and Snap bases have no application launcher."""
    return (app.source in (SOURCE_FLATPAK, SOURCE_SNAP)
            and not app.desktop_file and app.category == "System")

from sourcedock.i18n import t


def add_sensitive_removal_confirmation(content, button, applications, language):
    sensitive = {
        "apt", "dpkg", "sudo", "libc6", "systemd", "systemd-sysv", "udev", "gdm3",
        "python3", "python3-minimal", "python3-gi", "ubuntu-desktop", "zorin-os-desktop",
    }
    names = sorted({
        app.package_name for app in applications
        if is_system_component(app) or (is_native_source(app.source)
        and (
            app.package_name.split(":", 1)[0] in sensitive
            or app.package_name.startswith(("linux-image", "linux-headers"))
        ))
    })
    if not names:
        return
    expected = ", ".join(names)
    warning = Gtk.Label(label=t(language, "remove_system_component_warning" if any(is_system_component(app) for app in applications) else "remove_sensitive_warning"), xalign=0)
    warning.set_line_wrap(True)
    warning.get_style_context().add_class("danger-banner")
    content.pack_start(warning, False, False, 8)
    targets = Gtk.Label(label=expected, xalign=0)
    targets.set_line_wrap(True)
    targets.set_selectable(True)
    content.pack_start(targets, False, False, 0)
    confirmation = Gtk.Entry()
    confirmation.set_placeholder_text(expected)
    confirmation.set_tooltip_text(t(language, "remove_sensitive_confirm"))
    confirmation.get_accessible().set_name(t(language, "remove_sensitive_confirm"))
    confirmation.connect("changed", lambda entry: button.set_sensitive(entry.get_text() == expected))
    button.set_sensitive(False)
    content.pack_start(confirmation, False, False, 8)
