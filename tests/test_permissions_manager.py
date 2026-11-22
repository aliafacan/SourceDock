"""Permission manager command and folder parsing contracts."""

import subprocess
import unittest
from unittest.mock import Mock

from sourcedock.backend.manager import ApplicationRegistry


class TestPermissionManager(unittest.TestCase):
    def setUp(self):
        self.registry = object.__new__(ApplicationRegistry)
        self.registry.runner = Mock()

    def test_flatpak_folders_include_metadata_and_user_overrides(self):
        self.registry.runner.run.side_effect = [
            subprocess.CompletedProcess([], 0, "[Context]\nfilesystems=/base;home;\n", ""),
            subprocess.CompletedProcess([], 0, "[Context]\nfilesystems=/added;!/base;\n", ""),
        ]
        result = self.registry.flatpak_permissions("org.example.App")
        self.assertEqual(result["folders"], {"/base": False, "/added": True})
        self.assertTrue(result["filesystems"]["home"])

    def test_snap_connection_uses_actual_plug(self):
        self.registry.toggle_snap_connection("sample", "sample:camera", True)
        self.registry.runner.run_privileged.assert_called_once_with(
            ["snap", "connect", "sample:camera"], timeout=30,
        )

    def test_snap_connection_rejects_other_application_plug(self):
        with self.assertRaises(ValueError):
            self.registry.toggle_snap_connection("sample", "other:camera", False)
        self.registry.runner.run_privileged.assert_not_called()
