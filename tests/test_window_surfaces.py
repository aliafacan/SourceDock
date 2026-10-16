"""Window-surface contracts for independent SourceDock tool windows."""

import unittest
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from sourcedock.ui.components.common import load_dialog_data, make_window_movable
from sourcedock.ui.components.removal import add_sensitive_removal_confirmation
from sourcedock.core.models import SOURCE_APT, UnifiedApplication


class TestWindowSurfaces(unittest.TestCase):
    def test_cancelled_read_only_dialog_never_opens_a_late_result(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")
        parent = Gtk.Window()
        parent.preferences = SimpleNamespace(language="en")
        parent._show_error_dialog = MagicMock()
        show_result = MagicMock()
        release = threading.Event()
        queued = threading.Event()
        callbacks = []
        worker_threads = []

        def worker():
            worker_threads.append(threading.get_ident())
            release.wait(2)
            return "loaded"

        def queue(callback, *args):
            callbacks.append((callback, args))
            queued.set()

        loading = None
        try:
            with patch("sourcedock.ui.components.common.GLib.idle_add", side_effect=queue):
                loading = load_dialog_data(parent, "Details", worker, show_result)
                loading.response(Gtk.ResponseType.CANCEL)
                release.set()
                self.assertTrue(queued.wait(2))
            for callback, args in callbacks:
                callback(*args)
            self.assertNotEqual(worker_threads, [threading.get_ident()])
            show_result.assert_not_called()
            parent._show_error_dialog.assert_not_called()
        finally:
            release.set()
            if loading is not None:
                loading.destroy()
            parent.destroy()

    def test_bulk_removal_requires_every_sensitive_package_name(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button = Gtk.Button()
        applications = [
            UnifiedApplication(f"apt:{name}", name, SOURCE_APT, package_name=name)
            for name in ("editor", "systemd", "linux-image-example")
        ]
        try:
            add_sensitive_removal_confirmation(content, button, applications, "en")
            entry = next(widget for widget in content.get_children() if isinstance(widget, Gtk.Entry))
            self.assertFalse(button.get_sensitive())
            entry.set_text("systemd")
            self.assertFalse(button.get_sensitive())
            entry.set_text("linux-image-example, systemd")
            self.assertTrue(button.get_sensitive())
            entry.set_text("")
            self.assertFalse(button.get_sensitive())
        finally:
            content.destroy()
            button.destroy()

    def test_independent_window_is_detached_from_parent(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")

        parent = Gtk.Window()
        child = Gtk.Dialog(
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        try:
            make_window_movable(child, independent=True)

            self.assertIsNone(child.get_transient_for())
            self.assertFalse(child.get_modal())
            self.assertFalse(child.get_destroy_with_parent())
        finally:
            child.destroy()
            parent.destroy()

    def test_independent_flag_is_safe_when_movement_handler_already_exists(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")

        window = Gtk.Window()
        try:
            make_window_movable(window)
            window.set_modal(True)
            make_window_movable(window, independent=True)

            self.assertFalse(window.get_modal())
            self.assertIsNone(window.get_transient_for())
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
