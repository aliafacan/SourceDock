#!/usr/bin/env python3
"""MIME ve Sistem Entegrasyonu testleri."""

import os
from pathlib import Path
import tempfile
import unittest

from voltapp.backend.mime_integration import (
    PACKAGE_MIME_TYPES,
    get_icon_path,
    get_launcher_path,
    install_desktop_file,
    update_mimeapps_list,
)


class TestMimeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_package_mime_types_coverage(self):
        """Debian, RPM, AppImage ve Flatpak MIME türlerinin mevcut olduğunu doğrular."""
        self.assertIn("application/vnd.debian.binary-package", PACKAGE_MIME_TYPES)
        self.assertIn("application/x-deb", PACKAGE_MIME_TYPES)
        self.assertIn("application/x-rpm", PACKAGE_MIME_TYPES)
        self.assertIn("application/vnd.appimage", PACKAGE_MIME_TYPES)
        self.assertIn("application/x-appimage", PACKAGE_MIME_TYPES)
        self.assertIn("application/vnd.flatpak", PACKAGE_MIME_TYPES)
        self.assertIn("application/vnd.flatpak.ref", PACKAGE_MIME_TYPES)

    def test_install_desktop_file(self):
        """Desktop dosyasının doğru içerikle ve çalıştırılabilir formatta oluşturulduğunu doğrular."""
        dest_desktop = self.temp_path / "applications" / "voltapp.desktop"
        written_path = install_desktop_file(custom_dest=dest_desktop)

        self.assertTrue(written_path.exists())
        content = written_path.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", content)
        self.assertIn("Name=VoltApp", content)
        self.assertIn("Exec=", content)
        self.assertIn("%F", content)
        self.assertIn("MimeType=", content)
        self.assertIn("application/vnd.debian.binary-package", content)
        self.assertIn("application/vnd.appimage", content)
        self.assertIn("application/vnd.flatpak", content)
        self.assertIn("StartupWMClass=voltapp", content)

    def test_update_mimeapps_list_new_file(self):
        """Sıfırdan bir mimeapps.list oluşturulduğunda Default Applications bölümünün doğru eklendiğini doğrular."""
        mimeapps_path = self.temp_path / "mimeapps.list"
        update_mimeapps_list(custom_path=mimeapps_path)

        self.assertTrue(mimeapps_path.exists())
        content = mimeapps_path.read_text(encoding="utf-8")
        self.assertIn("[Default Applications]", content)
        self.assertIn("application/vnd.debian.binary-package=voltapp.desktop;", content)
        self.assertIn("application/vnd.appimage=voltapp.desktop;", content)
        self.assertIn("application/vnd.flatpak=voltapp.desktop;", content)

    def test_update_mimeapps_list_existing_file(self):
        """Mevcut bir mimeapps.list dosyasına voltapp.desktop'ın ilk sıraya eklendiğini doğrular."""
        mimeapps_path = self.temp_path / "mimeapps.list"
        mimeapps_path.write_text(
            "[Default Applications]\n"
            "text/plain=gedit.desktop;\n"
            "application/vnd.debian.binary-package=peazip.desktop;\n\n"
            "[Added Associations]\n"
            "application/vnd.debian.binary-package=peazip.desktop;\n",
            encoding="utf-8",
        )

        update_mimeapps_list(custom_path=mimeapps_path)
        content = mimeapps_path.read_text(encoding="utf-8")

        self.assertIn("text/plain=gedit.desktop;", content)
        self.assertIn("application/vnd.debian.binary-package=voltapp.desktop;peazip.desktop;", content)
        self.assertIn("application/vnd.appimage=voltapp.desktop;", content)

    def test_get_launcher_and_icon_paths(self):
        """Launcher ve ikon yollarının geçerli string döndürdüğünü doğrular."""
        launcher = get_launcher_path()
        self.assertTrue(len(launcher) > 0)
        icon = get_icon_path()
        self.assertTrue(len(icon) > 0)


if __name__ == "__main__":
    unittest.main()
