#!/usr/bin/env python3
"""Tests for ToastNotification and ToastHost components."""

import unittest
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from sourcedock.ui.components.toast import ToastNotification, ToastHost


class TestToastComponents(unittest.TestCase):
    def setUp(self):
        self.loop = GLib.MainContext.default()

    def _drain_events(self):
        while self.loop.pending():
            self.loop.iteration(False)

    def test_toast_notification_properties(self):
        closed = []
        toast = ToastNotification(
            "Operation finished",
            level="success",
            on_close=lambda: closed.append(True),
            language="tr",
        )
        self.assertIn("toast-box", toast.get_style_context().list_classes())
        self.assertIn("toast-success", toast.get_style_context().list_classes())
        self.assertEqual(toast.get_accessible().get_name(), "success: Operation finished")

        # GTK passes the clicked button to signal callbacks.
        toast._on_close_clicked(None)
        self.assertEqual(closed, [True])

        action_calls = []
        action_toast = ToastNotification(
            "Update available",
            action_label="Update",
            on_action=lambda: action_calls.append(True),
            on_close=lambda: closed.append(True),
            language="en",
        )
        action_toast._on_action_clicked(None)
        self.assertEqual(action_calls, [True])
        self.assertEqual(closed, [True, True])

    def test_toast_notification_levels(self):
        for level in ("info", "warning", "danger", "error", "success"):
            toast = ToastNotification("Msg", level=level, language="en")
            self.assertIn(f"toast-{level}", toast.get_style_context().list_classes())

    def test_toast_host_show_and_hide(self):
        child = Gtk.Label(label="Window Content")
        host = ToastHost(child, language="en")

        toast = host.show_toast("Item saved", level="info", timeout=0)
        self.assertIsNotNone(toast)
        self.assertTrue(host._revealer.get_reveal_child())
        self.assertEqual(host._current, toast)

        host.hide_toast()
        self.assertFalse(host._revealer.get_reveal_child())
        self.assertIsNone(host._current)

        toast = host.show_toast("Close me", timeout=0)
        toast._on_close_clicked(None)
        self.assertFalse(host._revealer.get_reveal_child())
        self.assertIsNone(host._current)

    def test_toast_host_replaces_previous(self):
        child = Gtk.Label(label="Content")
        host = ToastHost(child, language="tr")

        t1 = host.show_toast("First message", level="info", timeout=10)
        self.assertEqual(host._current, t1)

        t2 = host.show_toast("Second message", level="warning", timeout=10)
        self.assertEqual(host._current, t2)
        self.assertNotEqual(t1, t2)

        host.hide_toast()
        self.assertFalse(host._revealer.get_reveal_child())

    def test_toast_host_timeout_dismissal(self):
        child = Gtk.Label(label="Content")
        host = ToastHost(child, language="tr")

        host.show_toast("Auto dismiss", level="success", timeout=1)
        self.assertNotEqual(host._timeout_id, 0)
        self.assertTrue(host._revealer.get_reveal_child())

        # Simulate timeout trigger
        host._on_timeout()
        self.assertFalse(host._revealer.get_reveal_child())
        self.assertEqual(host._timeout_id, 0)


if __name__ == "__main__":
    unittest.main()

