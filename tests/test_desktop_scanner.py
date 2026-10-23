"""Regression tests for resilient desktop-entry discovery."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from sourcedock.backend.scanner import DesktopEntryScanner
from sourcedock.core.runner import CommandRunner


class TestDesktopEntryScanner(unittest.TestCase):
    def test_malformed_desktop_entry_is_ignored(self):
        runner = MagicMock(spec=CommandRunner)
        runner.read_text.return_value = "Version=1.0\nName=Broken entry\n"

        scanner = DesktopEntryScanner(runner)

        self.assertIsNone(scanner.load_entry("/usr/share/applications/broken.desktop"))

    def test_valid_entry_is_still_loaded_after_malformed_input(self):
        runner = MagicMock(spec=CommandRunner)
        runner.list_desktop_files.return_value = [
            "/usr/share/applications/broken.desktop",
            "/usr/share/applications/textmaker-free24.desktop",
        ]
        runner.read_text.side_effect = [
            "Version=1.0\nName=Broken entry\n",
            "[Desktop Entry]\nType=Application\nName=FreeOffice 2024 TextMaker\nExec=textmaker24free %F\n",
        ]
        scanner = DesktopEntryScanner(runner)

        entries = scanner.list_entries(["/usr/share/applications"])

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.name, "FreeOffice 2024 TextMaker")


if __name__ == "__main__":
    unittest.main()
