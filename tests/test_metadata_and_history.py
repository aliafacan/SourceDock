"""Metadata, history and package previews use isolated files and fake commands."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock

from sourcedock.backend.previews import (
    preview_deb_install,
    preview_install_plan,
    preview_rpm_install,
)
from sourcedock.core.history import OperationHistory
from sourcedock.core.json_store import write_json
from sourcedock.store.metadata import load_metadata
from sourcedock.ui.components.app_details_dialog import _read_desktop_comment


class TestMetadataAndHistory(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_appstream_localization_and_known_fields(self):
        path = self.root / "app.xml"
        path.write_text("""<component type="desktop-application"><id>org.example.App</id>
<name>Example</name><name xml:lang="tr">Ornek</name><pkgname>example</pkgname>
<launchable type="desktop-id">org.example.App.desktop</launchable>
<developer><name>Known developer</name></developer><project_license>GPL-3.0-only</project_license>
<url type="homepage">https://example.org</url><categories><category>Utility</category></categories></component>""")
        metadata = load_metadata([path], "tr")
        self.assertEqual(metadata["example"]["name"], "Ornek")
        self.assertEqual(metadata["org.example.App.desktop"]["identity"], "org.example.App")
        self.assertEqual(metadata["example"]["publisher"], "Known developer")
        self.assertEqual(metadata["example"]["license"], "GPL-3.0-only")
        self.assertEqual(metadata["example"]["screenshots"], [])

    def test_appstream_localization_falls_back_to_english_without_concatenating(self):
        path = self.root / "localized.xml"
        path.write_text(
            "<component><id>org.example.App</id>"
            "<description xml:lang=\"zh\">中文说明</description>"
            "<description xml:lang=\"en\">English description</description>"
            "</component>"
        )
        metadata = load_metadata([path], "tr")
        self.assertEqual(metadata["org.example.App"]["description"], "English description")

    def test_appstream_nested_localized_paragraphs_select_one_language(self):
        path = self.root / "nested.xml"
        path.write_text(
            "<component><id>org.example.Nested</id><description>"
            "<p>English original.</p><p xml:lang=\"zh\">中文。</p>"
            "<p xml:lang=\"tr\">Türkçe birinci.</p><p xml:lang=\"tr\">Türkçe ikinci.</p>"
            "</description></component>"
        )
        tr = load_metadata([path], "tr")
        en = load_metadata([path], "en")
        fr = load_metadata([path], "fr")
        self.assertEqual(tr["org.example.Nested"]["description"], "Türkçe birinci.\n\nTürkçe ikinci.")
        self.assertEqual(en["org.example.Nested"]["description"], "English original.")
        self.assertEqual(fr["org.example.Nested"]["description"], "English original.")

    def test_desktop_comment_locale_fallback_does_not_merge_languages(self):
        path = self.root / "example.desktop"
        path.write_text(
            "[Desktop Entry]\nType=Application\n"
            "Comment=English original\nComment[zh]=中文说明\nComment[tr]=Türkçe açıklama\n"
        )
        self.assertEqual(_read_desktop_comment(str(path), "tr_TR"), "Türkçe açıklama")
        self.assertEqual(_read_desktop_comment(str(path), "fr_FR"), "English original")

    def test_ambiguous_package_metadata_does_not_create_an_identity(self):
        path = self.root / "apps.xml"
        path.write_text(
            "<components><component><id>org.example.First</id><pkgname>shared</pkgname></component>"
            "<component><id>org.example.Second</id><pkgname>shared</pkgname></component></components>"
        )
        metadata = load_metadata([path])
        self.assertNotIn("shared", metadata)
        self.assertIn("org.example.First", metadata)

    def test_metadata_rejects_dtd_and_unsafe_homepage(self):
        path = self.root / "app.xml"
        path.write_text('<!DOCTYPE test [<!ENTITY test "value">]><component><id>test</id></component>')
        self.assertEqual(load_metadata([path]), {})
        path.write_text('<component><id>test</id><url type="homepage">file:///etc/passwd</url></component>')
        self.assertEqual(load_metadata([path])["test"]["homepage"], "")

    def test_history_redacts_and_supports_clear_and_export(self):
        history = OperationHistory(self.root / "history.json")
        history.append("Install", "APT", True, "token=hidden password=secret /home/example/file")
        data = history.load()
        self.assertNotIn("hidden", data[0]["message"])
        self.assertNotIn("secret", data[0]["message"])
        export = self.root / "export.json"
        history.export(export)
        self.assertEqual(json.loads(export.read_text()), data)
        history.clear()
        self.assertEqual(history.load(), [])

    def test_legacy_history_is_redacted_when_loaded_and_exported(self):
        history = OperationHistory(self.root / "history.json")
        history.path.write_text(json.dumps([{
            "time": "2026-10-16T09:00:00+00:00", "action": "Install", "source": "APT",
            "success": True, "message": "password=secret /home/another-user/private/file",
        }]))
        export = self.root / "export.json"
        history.export(export)
        text = export.read_text()
        self.assertNotIn("secret", text)
        self.assertNotIn("another-user", text)
        self.assertIn("~/private/file", text)

    def test_json_write_never_follows_a_temporary_symlink(self):
        path = self.root / "settings.json"
        victim = self.root / "important.txt"
        victim.write_text("keep")
        path.with_suffix(".tmp").symlink_to(victim)
        write_json(path, {"theme": "dark"})
        self.assertEqual(victim.read_text(), "keep")
        self.assertEqual(json.loads(path.read_text())["theme"], "dark")

    def test_install_preview_only_simulates_and_never_escalates(self):
        path = self.root / "test.deb"
        path.write_bytes(b"test fixture")
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = subprocess.CompletedProcess([], 0, "Inst test (1.0)", "")
        self.assertEqual(preview_deb_install(runner, str(path)), "Inst test (1.0)")
        command = runner.run.call_args.args[0]
        self.assertIn("--simulate", command)
        self.assertNotIn("sudo", command)
        runner.run_privileged.assert_not_called()

    def test_rpm_preview_prefers_dnf_and_never_escalates(self):
        path = self.root / "test.rpm"
        path.write_bytes(b"test fixture")
        runner = MagicMock()
        runner.command_exists.side_effect = lambda name: name == "dnf"
        runner.run.return_value = subprocess.CompletedProcess([], 1, "Dependencies resolved.", "")
        text = preview_rpm_install(runner, str(path))
        self.assertEqual(text, "Dependencies resolved.")
        command = runner.run.call_args.args[0]
        self.assertEqual(command[0], "dnf")
        self.assertIn("--assumeno", command)
        self.assertNotIn("install", command[0])
        runner.run_privileged.assert_not_called()

    def test_rpm_preview_falls_back_to_zypper_dry_run(self):
        path = self.root / "test.rpm"
        path.write_bytes(b"test fixture")
        runner = MagicMock()
        runner.command_exists.side_effect = lambda name: name == "zypper"
        runner.run.return_value = subprocess.CompletedProcess([], 0, "zypper plan", "")
        self.assertEqual(preview_rpm_install(runner, str(path)), "zypper plan")
        command = runner.run.call_args.args[0]
        self.assertEqual(command[:3], ["zypper", "--non-interactive", "install"])
        self.assertIn("--dry-run", command)

    def test_plan_dispatcher_reports_unsupported_formats_without_commands(self):
        class Info:
            format = "appimage"
            file_path = "/tmp/example.AppImage"

        runner = MagicMock()
        with self.assertRaises(Exception) as caught:
            preview_install_plan(runner, Info())
        self.assertIn("not available", str(caught.exception))
        runner.run.assert_not_called()
        runner.run_privileged.assert_not_called()

    def test_plan_dispatcher_routes_deb_and_rpm(self):
        class Info:
            def __init__(self, package_format, file_path):
                self.format = package_format
                self.file_path = file_path

        deb = self.root / "test.deb"
        deb.write_bytes(b"x")
        rpm = self.root / "test.rpm"
        rpm.write_bytes(b"x")
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = subprocess.CompletedProcess([], 0, "plan", "")
        self.assertEqual(preview_install_plan(runner, Info("deb", str(deb))), "plan")
        self.assertEqual(preview_install_plan(runner, Info("rpm", str(rpm))), "plan")
        runner.run_privileged.assert_not_called()


if __name__ == "__main__":
    unittest.main()
