#!/usr/bin/env python3
"""Zorin App Manager - giriş noktası."""

import sys
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from constants import APP_ICON_NAME, APP_TITLE
from preferences import PreferencesStore
from ui import AppManagerWindow

# WM_CLASS'ı desktop dosyasındaki StartupWMClass ile eşleştir
GLib.set_prgname(APP_ICON_NAME)
GLib.set_application_name(APP_TITLE)


def main() -> None:
    prefs_store = PreferencesStore()
    win = AppManagerWindow(prefs_store)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
