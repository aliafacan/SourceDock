"""Read-only source parsing and Flatpak icon discovery contracts."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sourcedock.backend.sources import _parse_apt_list_line, _parse_apt_sources_stanza
from sourcedock.core.icons import find_flatpak_icon_path, find_snap_icon_path


class TestSourceParsing(unittest.TestCase):
    def test_apt_list_line_keeps_uri_and_channel_details(self):
        row = _parse_apt_list_line(
            "deb [arch=amd64 signed-by=/etc/apt/keyrings/example.gpg] "
            "https://example.test/ubuntu noble main restricted",
            "example.list",
        )
        self.assertEqual(row[0:3], ("APT", "example.list", "https://example.test/ubuntu"))
        self.assertIn("arch=amd64", row[3])
        self.assertIn("noble main restricted", row[3])

    def test_deb822_sources_stanza_exposes_suite_components_architecture_and_state(self):
        rows = _parse_apt_sources_stanza(
            "Types: deb deb-src\n"
            "URIs: https://example.test/ubuntu https://mirror.example.test/ubuntu\n"
            "Suites: noble noble-updates\n"
            "Components: main restricted\n"
            "Architectures: amd64\n"
            "Enabled: yes\n",
            "example.sources",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2], "https://example.test/ubuntu")
        self.assertIn("deb deb-src", rows[0][3])
        self.assertIn("noble noble-updates", rows[0][3])
        self.assertIn("main restricted", rows[0][3])
        self.assertIn("arch=amd64", rows[0][3])
        self.assertIn("enabled=yes", rows[0][3])


class TestFlatpakIconDiscovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_exported_icon_is_preferred(self):
        path = self.root / "exports/share/icons/hicolor/128x128/apps/org.example.App.png"
        path.parent.mkdir(parents=True)
        path.touch()
        self.assertEqual(find_flatpak_icon_path("org.example.App", roots=(self.root,)), str(path))

    def test_hashed_appstream_icon_is_found(self):
        path = self.root / "appstream/flathub/x86_64/hash/icons/64x64/org.example.App.png"
        path.parent.mkdir(parents=True)
        path.touch()
        self.assertEqual(
            find_flatpak_icon_path("org.example.App", remote="flathub", roots=(self.root,)),
            str(path),
        )

    def test_installed_app_icon_is_found(self):
        path = self.root / (
            "app/org.example.App/x86_64/stable/files/share/icons/hicolor/48x48/apps/"
            "org.example.App.png"
        )
        path.parent.mkdir(parents=True)
        path.touch()
        self.assertEqual(find_flatpak_icon_path("org.example.App", roots=(self.root,)), str(path))

    def test_missing_icon_returns_empty_path(self):
        self.assertEqual(find_flatpak_icon_path("org.example.Missing", roots=(self.root,)), "")

    def test_untrusted_names_never_turn_into_icon_paths_or_glob_patterns(self):
        for app_id, remote in (
            ("../org.example.App", ""), ("org.example.*", ""), ("org.example.App", "../other"),
            ("org.example.App", "*"), ("/absolute/icon", ""),
        ):
            with self.subTest(app_id=app_id, remote=remote), patch.object(Path, "glob") as glob:
                self.assertEqual(find_flatpak_icon_path(app_id, remote, roots=(self.root,)), "")
                glob.assert_not_called()

    def test_metadata_generation_discovery_is_not_repeated_for_every_icon_size(self):
        original = Path.glob
        patterns = []

        def observe(path, pattern):
            patterns.append(pattern)
            return original(path, pattern)

        with patch.object(Path, "glob", observe):
            self.assertEqual(find_flatpak_icon_path("org.example.Missing", roots=(self.root,)), "")
        self.assertEqual(patterns.count("*/icons"), 4)
        self.assertFalse(any(pattern.startswith("*/icons/") for pattern in patterns))


class TestSnapIconDiscovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_snap_metadata_icon_is_found(self):
        path = Path(tempfile.mkdtemp(dir=self.root))
        icon = path / "demo/current/meta/gui/icon.png"
        icon.parent.mkdir(parents=True)
        icon.touch()
        self.assertEqual(find_snap_icon_path("demo", roots=(path,)), str(icon))

    def test_snap_name_cannot_escape_icon_root(self):
        self.assertEqual(find_snap_icon_path("../demo", roots=(self.root,)), "")


class TestRemoteManagement(unittest.TestCase):
    def test_remote_name_validation(self):
        from sourcedock.backend.sources import validate_remote_name

        self.assertTrue(validate_remote_name("flathub"))
        self.assertTrue(validate_remote_name("flathub-beta"))
        self.assertTrue(validate_remote_name("my_remote.1"))
        self.assertFalse(validate_remote_name(""))
        self.assertFalse(validate_remote_name("../escape"))
        self.assertFalse(validate_remote_name("remote;rm -rf /"))
        self.assertFalse(validate_remote_name("has spaces"))

    def test_remote_url_validation(self):
        from sourcedock.backend.sources import validate_remote_url

        self.assertTrue(validate_remote_url("https://dl.flathub.org/repo/flathub.flatpakrepo"))
        self.assertTrue(validate_remote_url("http://example.org/repo.flatpakrepo"))
        self.assertTrue(validate_remote_url("file:///opt/repo"))
        self.assertFalse(validate_remote_url(""))
        self.assertFalse(validate_remote_url("ftp://example.org"))
        self.assertFalse(validate_remote_url("https://example.org; echo evil"))
        self.assertFalse(validate_remote_url("https://example.org/$(whoami)"))

    def test_add_flatpak_remote_builds_fixed_argv(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import add_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        cmd = [
            "flatpak",
            "remote-add",
            "--if-not-exists",
            "--user",
            "flathub",
            "https://dl.flathub.org/repo/flathub.flatpakrepo",
        ]
        runner.run.return_value = subprocess.CompletedProcess(cmd, 0, "", "")

        ok, err = add_flatpak_remote(
            runner, "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo", user=True
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")
        runner.run.assert_called_once_with(cmd, timeout=30)

    def test_add_flatpak_remote_failure_propagates_stderr(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import add_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        cmd = ["flatpak", "remote-add", "--if-not-exists", "--user", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"]
        runner.run.return_value = subprocess.CompletedProcess(cmd, 1, "", "error: GPG verification failed")

        ok, err = add_flatpak_remote(runner, "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo", user=True)
        self.assertFalse(ok)
        self.assertEqual(err, "error: GPG verification failed")

    def test_add_flatpak_remote_handles_exception(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import add_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = subprocess.TimeoutExpired(cmd=["flatpak"], timeout=30)

        ok, err = add_flatpak_remote(runner, "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo", user=True)
        self.assertFalse(ok)
        self.assertIn("timed out", err.lower())

    def test_remove_flatpak_remote_builds_fixed_argv(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import remove_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        cmd = ["flatpak", "remote-delete", "--force", "--user", "flathub"]
        runner.run.return_value = subprocess.CompletedProcess(cmd, 0, "", "")

        ok, err = remove_flatpak_remote(runner, "flathub", user=True)
        self.assertTrue(ok)
        self.assertEqual(err, "")
        runner.run.assert_called_once_with(cmd, timeout=30)

    def test_remove_flatpak_remote_failure_propagates_stderr(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import remove_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        cmd = ["flatpak", "remote-delete", "--force", "--user", "flathub"]
        runner.run.return_value = subprocess.CompletedProcess(cmd, 1, "", "error: Remote flathub not found")

        ok, err = remove_flatpak_remote(runner, "flathub", user=True)
        self.assertFalse(ok)
        self.assertEqual(err, "error: Remote flathub not found")

    def test_remove_flatpak_remote_handles_exception(self):
        from unittest.mock import MagicMock
        from sourcedock.backend.sources import remove_flatpak_remote

        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = OSError("No such file or directory")

        ok, err = remove_flatpak_remote(runner, "flathub", user=True)
        self.assertFalse(ok)
        self.assertIn("No such file or directory", err)


if __name__ == "__main__":
    unittest.main()

