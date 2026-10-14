"""Metadata, history and package previews use isolated files and fake commands."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock

from sourcedock.backend.previews import preview_deb_install
from sourcedock.core.history import OperationHistory
from sourcedock.core.json_store import write_json
from sourcedock.store.metadata import load_metadata


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


if __name__ == "__main__":
    unittest.main()
