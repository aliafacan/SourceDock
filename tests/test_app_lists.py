"""Restoration plans reject guessed sources and malicious package identifiers."""

import json
import unittest
from unittest.mock import MagicMock

from sourcedock.backend.distro import DistroInfo
from sourcedock.core.app_lists import RestoreItem, export_applications, install_restore_item, plan_restore
from sourcedock.core.errors import BackendError
from sourcedock.core.models import SOURCE_APT, SOURCE_FLATPAK, UnifiedApplication


class TestApplicationLists(unittest.TestCase):
    def setUp(self):
        self.distro = DistroInfo(id="zorin", name="Zorin", native_manager=SOURCE_APT)
        self.native = UnifiedApplication(
            "apt:editor", "Editor", SOURCE_APT, package_name="editor", version="1"
        )
        self.flatpak = UnifiedApplication(
            "flatpak:editor", "Editor", SOURCE_FLATPAK, package_name="org.example.Editor", origin="flathub"
        )

    def test_export_roundtrip_keeps_source_and_remote(self):
        data = json.loads(export_applications([self.native, self.flatpak], self.distro))
        plan = plan_restore(data, self.distro, [])
        self.assertEqual(len(plan), 2)
        self.assertTrue(all(item.eligible for item in plan))
        self.assertEqual(plan[1].origin, "flathub")

    def test_different_distribution_requires_manual_review(self):
        data = json.loads(export_applications([self.native], self.distro))
        other = DistroInfo(id="debian", name="Debian", native_manager=SOURCE_APT)
        self.assertFalse(plan_restore(data, other, [])[0].eligible)

    def test_installed_identity_uses_source_and_package(self):
        data = json.loads(export_applications([self.native, self.flatpak], self.distro))
        plan = plan_restore(data, self.distro, [self.native])
        self.assertFalse(plan[0].eligible)
        self.assertTrue(plan[1].eligible)

    def test_legacy_lists_are_readable_without_assuming_native_compatibility(self):
        plan = plan_restore(
            [{"name": "Editor", "source": "apt", "package": "editor", "version": "1"}], self.distro, []
        )
        self.assertEqual(plan[0].reason, "restore_distro_mismatch")

    def test_untrusted_package_options_are_rejected(self):
        with self.assertRaises(BackendError):
            plan_restore([{"source": "apt", "package": "--allow-remove-essential"}], self.distro, [])
        registry = MagicMock()
        with self.assertRaises(BackendError):
            install_restore_item(registry, RestoreItem("Bad", "apt", "-y", ""))
        registry.runner.run_privileged.assert_not_called()

    def test_flatpak_restoration_uses_an_explicit_user_remote(self):
        registry = MagicMock()
        install_restore_item(registry, RestoreItem("Editor", "flatpak", "org.example.Editor", "", "flathub"))
        command = registry.runner.run.call_args.args[0]
        self.assertIn("--user", command)
        self.assertIn("flathub", command)
        registry.runner.run_privileged.assert_not_called()


if __name__ == "__main__":
    unittest.main()
