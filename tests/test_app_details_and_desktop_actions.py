#!/usr/bin/env python3
"""Uygulama detay sayfası (App Details) ve masaüstü menüsü eylemleri (Desktop Actions) testleri."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from voltapp.constants import APP_VERSION
from voltapp.core.models import SOURCE_APT, SOURCE_FLATPAK, UnifiedApplication
from voltapp.ui.components.app_details_dialog import _format_size, _read_desktop_comment


class TestAppDetailsDialogHelpers(unittest.TestCase):
    """Detay sayfası yardımcı fonksiyonları testleri."""

    def test_format_size(self):
        self.assertEqual(_format_size(None), "-")
        self.assertEqual(_format_size(0), "-")
        self.assertEqual(_format_size(500), "500 KB")
        self.assertEqual(_format_size(2048), "2.0 MB")
        self.assertEqual(_format_size(1024 * 1024 * 2), "2.00 GB")

    def test_read_desktop_comment(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".desktop", delete=False) as f:
            f.write("""[Desktop Entry]
Name=TestApp
Comment=Test Description
Comment[tr]=Test Açıklaması
Comment[en]=Test Description EN
Exec=testapp
""")
            f_path = f.name

        try:
            tr_desc = _read_desktop_comment(f_path, "tr")
            self.assertEqual(tr_desc, "Test Açıklaması")

            en_desc = _read_desktop_comment(f_path, "en")
            self.assertEqual(en_desc, "Test Description EN")
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)


class TestDesktopActionsAndVersion(unittest.TestCase):
    """Masaüstü kısayolu eylemleri ve sürüm 1.1.0 testleri."""

    def test_version_bump(self):
        self.assertEqual(APP_VERSION, "1.1.0")

        deb_script = Path("packaging/build_deb.sh").read_text(encoding="utf-8")
        self.assertIn('VERSION="1.1.0"', deb_script)

    def test_desktop_actions_present(self):
        desktop_file = Path("packaging/voltapp.desktop")
        self.assertTrue(desktop_file.exists())
        content = desktop_file.read_text(encoding="utf-8")

        self.assertIn("Actions=Details;Uninstall;Updates;", content)
        self.assertIn("[Desktop Action Details]", content)
        self.assertIn("--details voltapp", content)
        self.assertIn("[Desktop Action Uninstall]", content)
        self.assertIn("--uninstall voltapp", content)
        self.assertIn("[Desktop Action Updates]", content)
        self.assertIn("--updates", content)


if __name__ == "__main__":
    unittest.main()

