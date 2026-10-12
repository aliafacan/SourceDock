#!/usr/bin/env python3
"""VoltApp ⚡ - Giriş noktası (Entry Point)."""

import sys
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
    prefs_store = PreferencesStore()
    win = MainWindow(prefs_store)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
