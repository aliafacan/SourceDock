"""Permission switches reflect only completed backend changes."""

import unittest
from unittest.mock import Mock

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from sourcedock.core.errors import AuthRequiredError
from sourcedock.core.models import SOURCE_FLATPAK, SOURCE_SNAP, UnifiedApplication
from sourcedock.ui.components.permissions_dialog import PermissionsDialog


class CachedParent(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.password = None

    def get_cached_sudo_password(self):
        return self.password

    def set_cached_sudo_password(self, password):
        self.password = password

    def clear_cached_sudo_password(self):
        self.password = None


class TestPermissionsDialog(unittest.TestCase):
    def setUp(self):
        if not Gtk.init_check()[0]:
            self.skipTest("A GTK display is required.")
        self.parent = CachedParent()
        self.addCleanup(self.parent.destroy)
        self.registry = Mock()

    def _dialog(self, source):
        data = (
            {"filesystems": {}, "shares": {}, "sockets": {}, "devices": {}, "folders": {}}
            if source == SOURCE_FLATPAK
            else {"connections": [{
                "interface": "home", "plug": "sample:home", "slot": ":home", "connected": False,
            }]}
        )
        app = UnifiedApplication(id="sample", name="Sample", source=source, package_name="sample")
        dialog = PermissionsDialog(self.parent, app, self.registry, data)
        self.addCleanup(dialog.destroy)
        return dialog

    @staticmethod
    def _switches(widget):
        if isinstance(widget, Gtk.Switch):
            return [widget]
        if isinstance(widget, Gtk.Container):
            return [switch for child in widget.get_children()
                    for switch in TestPermissionsDialog._switches(child)]
        return []

    def test_flatpak_switch_updates_both_gtk_states_and_rolls_back_on_error(self):
        dialog = self._dialog(SOURCE_FLATPAK)
        switch = self._switches(dialog)[0]
        switch.set_active(True)
        self.assertEqual((switch.get_active(), switch.get_state()), (True, True))
        self.registry.set_flatpak_override.assert_called_with("sample", "filesystem", "home")

        dialog._show_error = Mock()
        self.registry.set_flatpak_override.side_effect = RuntimeError("denied")
        switch.set_active(False)
        self.assertEqual((switch.get_active(), switch.get_state()), (True, True))

    def test_snap_cancelled_password_keeps_switch_off(self):
        dialog = self._dialog(SOURCE_SNAP)
        switch = self._switches(dialog)[0]
        self.registry.toggle_snap_connection.side_effect = AuthRequiredError("password required")
        dialog._ask_permission_password = Mock(return_value=None)

        switch.set_active(True)

        self.assertEqual((switch.get_active(), switch.get_state()), (False, False))
        self.assertIsNone(self.parent.password)
        dialog._ask_permission_password.assert_called_once()
        self.registry.runner.clear_sudo_password.assert_called_once()

    def test_snap_password_is_reused_for_next_toggle(self):
        dialog = self._dialog(SOURCE_SNAP)
        switch = self._switches(dialog)[0]
        self.registry.toggle_snap_connection.side_effect = [AuthRequiredError("password required"), None, None]
        dialog._ask_permission_password = Mock(return_value="secret")

        switch.set_active(True)
        self.assertEqual((switch.get_active(), switch.get_state()), (True, True))
        self.assertEqual(self.parent.password, "secret")

        switch.set_active(False)
        self.assertEqual((switch.get_active(), switch.get_state()), (False, False))
        dialog._ask_permission_password.assert_called_once()
        self.assertEqual(self.registry.toggle_snap_connection.call_count, 3)
        self.registry.set_sudo_password.assert_called_with("secret")


if __name__ == "__main__":
    unittest.main()
