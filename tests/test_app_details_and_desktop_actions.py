#!/usr/bin/env python3
"""Uygulama detay sayfası (App Details) ve masaüstü menüsü eylemleri (Desktop Actions) testleri."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from sourcedock import __version__
from sourcedock.constants import (
    APP_COMMAND,
    APP_DESKTOP_ID,
    APP_PACKAGE_NAME,
    APP_TITLE,
    APP_VERSION,
    LEGACY_APP_COMMAND,
)
from sourcedock.core.models import SOURCE_APT, SOURCE_FLATPAK, UnifiedApplication
from sourcedock.ui.components.app_details_dialog import _format_size, _read_desktop_comment


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
    """Masaüstü kısayolu eylemleri ve sürüm tutarlılığı testleri."""

    def test_version_bump(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, APP_VERSION)

    def test_sourcedock_identity_and_legacy_command_contract(self):
        self.assertEqual(APP_TITLE, "SourceDock")
        self.assertEqual(APP_COMMAND, "sourcedock")
        self.assertEqual(APP_DESKTOP_ID, "sourcedock.desktop")
        self.assertEqual(APP_PACKAGE_NAME, "sourcedock")
        self.assertEqual(LEGACY_APP_COMMAND, "voltapp")
        build_script = Path("packaging/build_deb.sh").read_text(encoding="utf-8")
        self.assertIn('cat > "$DEB_ROOT/usr/bin/voltapp"', build_script)
        self.assertIn("Replaces: voltapp", build_script)

    def test_desktop_actions_present(self):
        desktop_file = Path("packaging/sourcedock.desktop")
        self.assertTrue(desktop_file.exists())
        content = desktop_file.read_text(encoding="utf-8")

        self.assertIn("Actions=Details;Uninstall;Updates;", content)
        self.assertIn("[Desktop Action Details]", content)
        self.assertIn("--details sourcedock", content)
        self.assertIn("[Desktop Action Uninstall]", content)
        self.assertIn("--uninstall sourcedock", content)
        self.assertIn("[Desktop Action Updates]", content)
        self.assertIn("--updates", content)

    def test_gnome_shell_right_click_extension_packaged(self):
        """Ubuntu/Zorin uygulama menüsü sağ tık entegrasyonunun paketlendiğini doğrular."""
        metadata = Path("sourcedock/desktop/extension/metadata.json")
        extension = Path("sourcedock/desktop/extension/extension.js")
        build_script = Path("packaging/build_deb.sh").read_text(encoding="utf-8")
        install_script = Path("install.sh").read_text(encoding="utf-8")
        uninstall_script = Path("uninstall.sh").read_text(encoding="utf-8")

        self.assertTrue(metadata.exists())
        self.assertTrue(extension.exists())
        self.assertIn('"uuid": "sourcedock-menu@aliafacan.dev"', metadata.read_text(encoding="utf-8"))
        extension_js = extension.read_text(encoding="utf-8")
        self.assertIn("AppMenu.prototype.setApp", extension_js)
        self.assertIn("--details", extension_js)
        self.assertIn("--uninstall", extension_js)
        self.assertIn("/usr/share/gnome-shell/extensions/$EXTENSION_UUID", build_script)
        self.assertIn("/usr/share/gnome-shell/extensions/$EXTENSION_UUID", install_script)
        self.assertIn("/usr/share/gnome-shell/extensions/sourcedock-menu@aliafacan.dev", uninstall_script)


if __name__ == "__main__":
    unittest.main()
