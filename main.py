#!/usr/bin/env python3
"""VoltApp ⚡ - Giriş noktası (Entry Point)."""

import os
import sys

# VS Code / Snap ortamlarından çalıştırıldığında snap kütüphanelerinin sızmasını önleme
if not os.environ.get("_VOLTAPP_CLEAN_ENV"):
    _clean_env = dict(os.environ)
    _clean_env["_VOLTAPP_CLEAN_ENV"] = "1"
    _needs_restart = False

    # Snap'e ait GTK ve modül değişkenlerini temizle
    _SNAP_VARS = (
        "GTK_PATH", "GTK3_MODULES", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
        "GDK_PIXBUF_MODULEDIR", "GDK_PIXBUF_MODULE_FILE", "GIO_MODULE_DIR",
        "GSETTINGS_SCHEMA_DIR", "LOCPATH",
    )
    for _var in _SNAP_VARS:
        if _var in _clean_env:
            del _clean_env[_var]
            _needs_restart = True

    # Snap sanal ev dizinine yönlendirilmiş XDG değişkenlerini temizle
    for _xdg_var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        if _xdg_var in _clean_env and "/snap/" in _clean_env[_xdg_var]:
            del _clean_env[_xdg_var]
            _needs_restart = True

    if "XDG_DATA_DIRS" in _clean_env and "/snap/" in _clean_env["XDG_DATA_DIRS"]:
        _parts = [p for p in _clean_env["XDG_DATA_DIRS"].split(":") if "/snap/" not in p and p.strip()]
        _clean_env["XDG_DATA_DIRS"] = ":".join(_parts)
        _needs_restart = True

    if "LD_LIBRARY_PATH" in _clean_env and "/snap/" in _clean_env["LD_LIBRARY_PATH"]:
        _parts = [p for p in _clean_env["LD_LIBRARY_PATH"].split(":") if "/snap/" not in p and p.strip()]
        if _parts:
            _clean_env["LD_LIBRARY_PATH"] = ":".join(_parts)
        else:
            del _clean_env["LD_LIBRARY_PATH"]
        _needs_restart = True

    # Snap üst kimlik değişkenlerini temizle
    for _svar in list(_clean_env.keys()):
        if _svar.startswith("SNAP_") and _svar != "SNAP_REAL_HOME":
            del _clean_env[_svar]
            _needs_restart = True

    if _needs_restart and (not sys.argv or sys.argv[0] != "-c"):
        args = [sys.executable, os.path.abspath(__file__)] + sys.argv[1:]
        os.execve(sys.executable, args, _clean_env)

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from voltapp.constants import APP_ICON_NAME, APP_TITLE
from voltapp.preferences import PreferencesStore
from voltapp.ui.window import MainWindow

# WM_CLASS ayarları
GLib.set_prgname(APP_ICON_NAME)
GLib.set_application_name(APP_TITLE)


def main() -> None:
    if "--register-mime" in sys.argv:
        from voltapp.backend.mime_integration import set_as_default_package_handler
        ok, msg = set_as_default_package_handler()
        print(msg)
        sys.exit(0 if ok else 1)

    prefs_store = PreferencesStore()

    # Dosya yöneticisinden çift tıklanarak veya terminalden paket dosyası verildiyse aç
    target_files: list[str] = []
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        cleaned = arg
        if cleaned.startswith("file://"):
            try:
                filename, _ = GLib.filename_from_uri(cleaned)
                cleaned = filename
            except Exception:
                cleaned = cleaned.replace("file://", "")
        cleaned = os.path.abspath(cleaned)
        if os.path.exists(cleaned) and os.path.isfile(cleaned):
            target_files.append(cleaned)

    if target_files:
        # STANDALONE MINI-INSTALLER:
        # Büyük ana pencere açılmaz; sadece şık, hafif mini kurulum penceresi açılır!
        from gi.repository import Gdk
        from voltapp.backend.manager import ApplicationRegistry
        from voltapp.ui.components.package_installer_dialog import PackageInstallerDialog
        from voltapp.theme import get_theme_css
        from voltapp.i18n import t

        target_file = target_files[0]
        prefs = prefs_store.load()
        lang = prefs.language
        registry = ApplicationRegistry()

        # Tema ayarlarını ekrana uygula
        is_dark = prefs.theme == "dark"
        try:
            def_settings = Gtk.Settings.get_default()
            if def_settings:
                def_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
            screen = Gdk.Screen.get_default()
            if screen:
                scr_settings = Gtk.Settings.get_for_screen(screen)
                if scr_settings:
                    scr_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
                provider = Gtk.CssProvider()
                provider.load_from_data(get_theme_css(prefs.theme, getattr(prefs, "scale", "100")).encode("utf-8"))
                Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception:
            pass

        try:
            pkg_info = registry.inspect_local_package(target_file)
            pkg_status = registry.get_local_package_status(pkg_info)
        except Exception as exc:
            err_dialog = Gtk.MessageDialog(
                title=APP_TITLE,
                text=f"{t(lang, 'package_inspect_failed')}: {exc}",
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
            )
            err_dialog.run()
            err_dialog.destroy()
            sys.exit(1)

        installer = PackageInstallerDialog(
            parent=None,
            info=pkg_info,
            language=lang,
            is_installed=pkg_status.is_installed,
            pkg_status=pkg_status,
            registry=registry,
            standalone=True,
        )
        installer.show_all()
        Gtk.main()
        sys.exit(0)

    win = MainWindow(prefs_store)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

