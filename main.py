#!/usr/bin/env python3
"""SourceDock - Giriş noktası (Entry Point)."""

import os
import sys

# VS Code / Snap ortamlarından çalıştırıldığında snap kütüphanelerinin sızmasını önleme
if not os.environ.get("_SOURCEDOCK_CLEAN_ENV"):
    _clean_env = dict(os.environ)
    _clean_env["_SOURCEDOCK_CLEAN_ENV"] = "1"
    _needs_restart = False

    # Snap'e ait GTK ve modül değişkenlerini temizle
    _SNAP_VARS = (
        "GTK_PATH",
        "GTK3_MODULES",
        "GTK_EXE_PREFIX",
        "GTK_IM_MODULE_FILE",
        "GDK_PIXBUF_MODULEDIR",
        "GDK_PIXBUF_MODULE_FILE",
        "GIO_MODULE_DIR",
        "GSETTINGS_SCHEMA_DIR",
        "LOCPATH",
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

from sourcedock.constants import (
    APP_COMMAND,
    APP_DESKTOP_ID,
    APP_ICON_NAME,
    APP_PACKAGE_NAME,
    APP_TITLE,
    APP_VERSION,
    LEGACY_APP_COMMAND,
    LEGACY_APP_DESKTOP_ID,
)
from sourcedock.preferences import PreferencesStore
from sourcedock.theme import get_theme_css, resolve_theme
from sourcedock.ui.window import MainWindow

# WM_CLASS ayarları
GLib.set_prgname(APP_ICON_NAME)
GLib.set_application_name(APP_TITLE)


def main() -> None:
    if "--version" in sys.argv:
        print(APP_VERSION)
        return
    if "--help" in sys.argv:
        import argparse

        parser = argparse.ArgumentParser(
            prog=APP_COMMAND, description="Linux application and package manager"
        )
        parser.add_argument("file", nargs="?", help="Preview a local package")
        parser.add_argument("--details", metavar="DESKTOP_ID", help="Show installed application details")
        parser.add_argument("--uninstall", metavar="DESKTOP_ID", help="Confirm application removal")
        parser.add_argument("--updates", action="store_true", help="Open the updates center")
        parser.add_argument("--version", action="store_true", help="Print version")
        parser.print_help()
        return
    if os.geteuid() == 0:
        print(
            "Run SourceDock from your normal user session. Administrator access is requested for package operations.",
            file=sys.stderr,
        )
        sys.exit(1)
    if "--register-mime" in sys.argv:
        from sourcedock.backend.mime_integration import set_as_default_package_handler

        ok, msg = set_as_default_package_handler()
        print(msg)
        sys.exit(0 if ok else 1)

    prefs_store = PreferencesStore()

    # appstream:// URI desteği
    for arg in list(sys.argv[1:]):
        if arg.startswith("appstream://") or arg.startswith("appstream:"):
            app_id = arg.replace("appstream://", "").replace("appstream:", "").strip()
            sys.argv = [sys.argv[0], "--details", app_id]
            break

    # Uygulama Ayrıntıları (App Details)
    if "--details" in sys.argv:
        from gi.repository import Gdk
        from sourcedock.backend.manager import ApplicationRegistry
        from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog
        from sourcedock.core.models import UnifiedApplication

        prefs = prefs_store.load()
        lang = prefs.language
        registry = ApplicationRegistry()

        try:
            is_dark = resolve_theme(prefs.theme) == "dark"
            def_settings = Gtk.Settings.get_default()
            if def_settings:
                def_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
            screen = Gdk.Screen.get_default()
            if screen:
                scr_settings = Gtk.Settings.get_for_screen(screen)
                if scr_settings:
                    scr_settings.set_property("gtk-application-prefer-dark-theme", is_dark)
                provider = Gtk.CssProvider()
                provider.load_from_data(
                    get_theme_css(prefs.theme, getattr(prefs, "scale", "100")).encode("utf-8")
                )
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception:
            pass

        idx = sys.argv.index("--details")
        target_name = (
            sys.argv[idx + 1]
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-")
            else APP_COMMAND
        )

        target_app = registry.find_application(target_name)
        if not target_app and target_name.lower() in (
            APP_COMMAND,
            APP_DESKTOP_ID,
            LEGACY_APP_COMMAND,
            LEGACY_APP_DESKTOP_ID,
        ):
            target_app = UnifiedApplication(
                id=f"apt:{APP_PACKAGE_NAME}",
                name=APP_TITLE,
                source="apt",
                version=APP_VERSION,
                icon=APP_ICON_NAME,
                executable=f"/usr/bin/{APP_COMMAND}",
                desktop_file=f"/usr/share/applications/{APP_DESKTOP_ID}",
                install_path=f"/usr/lib/{APP_PACKAGE_NAME}",
                category="System",
                package_name=APP_PACKAGE_NAME,
                update_available=False,
            )
        elif not target_app:
            print(f"Installed application could not be identified: {target_name}", file=sys.stderr)
            sys.exit(1)

        dialog = InstalledAppDetailsDialog(
            application=target_app,
            registry=registry,
            language=lang,
            parent=None,
            standalone=True,
        )
        dialog.show_all()
        Gtk.main()
        sys.exit(0)

    # Uygulamayı Kaldır (Uninstall CLI/Action)
    if "--uninstall" in sys.argv:
        from gi.repository import Gdk
        from sourcedock.backend.manager import ApplicationRegistry
        from sourcedock.i18n import t

        prefs = prefs_store.load()
        lang = prefs.language
        registry = ApplicationRegistry()

        try:
            screen = Gdk.Screen.get_default()
            if screen:
                provider = Gtk.CssProvider()
                provider.load_from_data(
                    get_theme_css(prefs.theme, getattr(prefs, "scale", "100")).encode("utf-8")
                )
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception:
            pass

        idx = sys.argv.index("--uninstall")
        target_name = (
            sys.argv[idx + 1]
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-")
            else APP_COMMAND
        )

        app = registry.find_application(target_name)
        display_name = app.name if app else target_name.replace(".desktop", "").capitalize()

        confirm = Gtk.MessageDialog(
            title=APP_TITLE,
            type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=t(lang, "details_remove_confirm_title"),
        )
        confirm.format_secondary_text(t(lang, "details_remove_confirm_text", name=display_name))
        confirm.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        del_btn = confirm.add_button(t(lang, "details_btn_remove"), Gtk.ResponseType.OK)
        del_btn.get_style_context().add_class("destructive-action")
        confirm.show_all()
        resp = confirm.run()
        confirm.destroy()

        if resp == Gtk.ResponseType.OK:
            if target_name.lower() in (
                APP_COMMAND,
                APP_DESKTOP_ID,
                LEGACY_APP_COMMAND,
                LEGACY_APP_DESKTOP_ID,
            ):
                uninstall_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uninstall.sh")
                if os.path.exists(uninstall_script):
                    registry.runner.run_privileged(["bash", uninstall_script])
                else:
                    registry.runner.run_privileged(["apt-get", "remove", "-y", APP_PACKAGE_NAME])
            elif app:
                registry.remove(app)
            else:
                print(f"Installed application could not be identified: {target_name}", file=sys.stderr)
                sys.exit(1)
        sys.exit(0)

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
        from sourcedock.backend.manager import ApplicationRegistry
        from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
        from sourcedock.i18n import t

        target_file = target_files[0]
        prefs = prefs_store.load()
        lang = prefs.language
        registry = ApplicationRegistry()

        # Tema ayarlarını ekrana uygula
        is_dark = resolve_theme(prefs.theme) == "dark"
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
                provider.load_from_data(
                    get_theme_css(prefs.theme, getattr(prefs, "scale", "100")).encode("utf-8")
                )
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
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
