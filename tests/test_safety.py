"""Adversarial tests run only against disposable files and subprocesses."""

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import threading
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from sourcedock.backend.archive_safety import safe_extract_archive
from sourcedock.backend.local_packages import inspect_appimage, install_local_archive
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.portable import (
    PortableProvider,
    load_portable_registry,
    register_portable_app,
    save_portable_registry,
)
from sourcedock.core.errors import BackendError
from sourcedock.core.models import (
    ApplicationSnapshot,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_PORTABLE,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.core.process import critical_command


class TestFileSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")})
        environment.start()
        self.addCleanup(environment.stop)
        self.runner = MagicMock()
        self.runner.command_exists.return_value = False

    def _registered_app(self):
        root = self.root / "apps"
        path = root / "demo"
        path.mkdir(parents=True)
        (path / "demo").write_text("#!/bin/sh\nexit 0\n")
        register_portable_app("Demo", "1.0", str(path), str(path / "demo"), "", managed_root=str(root))
        return PortableProvider(self.runner).list_applications()[0]

    def test_portable_removal_rejects_manipulated_documents_path(self):
        app = self._registered_app()
        documents = self.root / "Documents"
        documents.mkdir()
        valuable = documents / "important.txt"
        valuable.write_text("keep")
        registry = load_portable_registry()
        registry[app.id]["install_path"] = str(documents)
        registry[app.id]["managed_root"] = str(self.root)
        save_portable_registry(registry)
        malicious = UnifiedApplication(app.id, app.name, SOURCE_PORTABLE, install_path=str(documents))
        with self.assertRaises(BackendError):
            PortableProvider(self.runner).remove(malicious)
        self.assertEqual(valuable.read_text(), "keep")
        self.assertIn(app.id, load_portable_registry())

    def test_portable_removal_rejects_symlink_and_keeps_registry(self):
        app = self._registered_app()
        path = Path(app.install_path)
        moved = path.with_name("original")
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(BackendError):
            PortableProvider(self.runner).remove(app)
        self.assertTrue((moved / "demo").exists())
        self.assertIn(app.id, load_portable_registry())

    def test_portable_removal_does_not_swallow_io_failure(self):
        app = self._registered_app()
        with patch("sourcedock.backend.portable.shutil.rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(BackendError):
                PortableProvider(self.runner).remove(app)
        self.assertIn(app.id, load_portable_registry())

    def test_portable_removal_requires_manifest(self):
        app = self._registered_app()
        (Path(app.install_path) / ".sourcedock-managed.json").unlink()
        with self.assertRaises(BackendError):
            PortableProvider(self.runner).remove(app)
        self.assertTrue(Path(app.install_path).exists())

    def test_portable_removal_rejects_foreign_shortcut(self):
        app = self._registered_app()
        registry = load_portable_registry()
        registry[app.id]["desktop_file"] = str(self.root / "foreign.desktop")
        save_portable_registry(registry)
        with self.assertRaises(BackendError):
            PortableProvider(self.runner).remove(app)
        self.assertTrue(Path(app.install_path).exists())

    def test_zip_traversal_and_absolute_paths_are_rejected(self):
        for name in ("../apps-copy/evil", "app/../evil", "/tmp/evil", "C:/evil", "..\\evil"):
            with self.subTest(name=name):
                archive = self.root / "bad.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr(name, "bad")
                with self.assertRaises(BackendError):
                    safe_extract_archive(str(archive), self.root / "extract")
        self.assertFalse((self.root / "apps-copy").exists())

    def test_zip_symlink_is_rejected(self):
        archive = self.root / "bad.zip"
        member = zipfile.ZipInfo("link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(member, "../outside")
        with self.assertRaises(BackendError):
            safe_extract_archive(str(archive), self.root / "extract")

    def test_tar_links_and_special_files_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                archive = self.root / "bad.tar"
                with tarfile.open(archive, "w") as output:
                    member = tarfile.TarInfo("link")
                    member.type = kind
                    member.linkname = "../outside"
                    output.addfile(member)
                with self.assertRaises(BackendError):
                    safe_extract_archive(str(archive), self.root / "extract")

    def test_extraction_rejects_existing_symlink(self):
        destination = self.root / "extract"
        destination.mkdir()
        (destination / "nested").symlink_to(self.root, target_is_directory=True)
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("nested/evil", "bad")
        with self.assertRaises(BackendError):
            safe_extract_archive(str(archive), destination)
        self.assertFalse((self.root / "evil").exists())

    def test_extraction_is_bounded_before_writing(self):
        archive = self.root / "large.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("data", "x" * 20)
        with patch("sourcedock.backend.archive_safety.MAX_FILE_BYTES", 10):
            with self.assertRaises(BackendError):
                safe_extract_archive(str(archive), self.root / "extract")
        self.assertFalse((self.root / "extract/data").exists())

    def test_compression_bomb_is_rejected(self):
        archive = self.root / "bomb.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("data", b"x" * (2 * 1024 * 1024))
        with self.assertRaises(BackendError):
            safe_extract_archive(str(archive), self.root / "extract")

    def test_invalid_upgrade_keeps_the_previous_installation(self):
        archive = self.root / "demo-1.0.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("demo", "#!/bin/sh\nexit 0\n")
        installed, executable = install_local_archive(self.runner, str(archive), create_desktop=False)
        previous = Path(executable).read_bytes()
        bad = self.root / "demo-2.0.zip"
        with zipfile.ZipFile(bad, "w") as output:
            output.writestr("../outside", "bad")
        with self.assertRaises(BackendError):
            install_local_archive(self.runner, str(bad), create_desktop=False)
        self.assertEqual(Path(executable).read_bytes(), previous)
        self.assertEqual(load_portable_registry()["portable:demo"]["version"], "1.0")

    def test_appimage_inspection_never_executes_or_chmods_the_file(self):
        marker = self.root / "executed"
        image = self.root / "demo-1.0.AppImage"
        image.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        image.chmod(0o644)
        with patch("sourcedock.backend.local_packages.subprocess.run") as run:
            info = inspect_appimage(self.runner, str(image))
        run.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertEqual(stat.S_IMODE(image.stat().st_mode), 0o644)
        self.assertEqual(info.extra_info["verification"], "unverified")
        self.assertEqual(info.architecture, "")

    def test_registration_failure_restores_previous_executable_and_shortcut(self):
        archive = self.root / "demo-1.0.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("demo", "#!/bin/sh\nexit 0\n")
        installed, executable = install_local_archive(self.runner, str(archive))
        registry = load_portable_registry()
        previous_desktop = Path(registry["portable:demo"]["desktop_file"]).read_bytes()
        previous_executable = Path(executable).read_bytes()
        upgrade = self.root / "demo-2.0.zip"
        with zipfile.ZipFile(upgrade, "w") as output:
            output.writestr("demo", "#!/bin/sh\nexit 1\n")
        with patch(
            "sourcedock.backend.local_packages.register_portable_app",
            side_effect=BackendError("write failed"),
        ):
            with self.assertRaises(BackendError):
                install_local_archive(self.runner, str(upgrade))
        self.assertEqual(Path(executable).read_bytes(), previous_executable)
        self.assertEqual(Path(registry["portable:demo"]["desktop_file"]).read_bytes(), previous_desktop)
        self.assertEqual(load_portable_registry(), registry)

    def test_corrupt_registry_record_is_not_deleted_or_used_as_a_path(self):
        save_portable_registry({"portable:broken": {"install_path": ["bad"], "name": None}})
        self.assertEqual(PortableProvider(self.runner).list_applications(), [])
        self.assertIn("portable:broken", load_portable_registry())

    def test_missing_installation_does_not_silently_prune_a_failed_removal(self):
        app = self._registered_app()
        Path(app.executable).unlink()
        self.assertEqual(PortableProvider(self.runner).list_applications()[0].id, app.id)
        self.assertIn(app.id, load_portable_registry())


class TestProcessSafety(unittest.TestCase):
    def test_daemon_and_local_package_transactions_are_critical(self):
        for command in (["snap", "install", "demo"], ["sudo", "-S", "rpm", "-U", "demo.rpm"]):
            with self.subTest(command=command):
                self.assertTrue(critical_command(command))
        self.assertFalse(critical_command(["sleep", "1"]))

    def test_silent_process_has_an_absolute_timeout(self):
        runner = CommandRunner()
        started = time.monotonic()
        with self.assertRaises(BackendError):
            runner._run_streaming([sys.executable, "-c", "import time; time.sleep(10)"], 0.2, True)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNone(runner._current_process)

    def test_streams_partial_lines_and_redacts_secrets(self):
        runner = CommandRunner()
        runner.set_sudo_password("test-sensitive-value")
        lines = []
        runner.set_output_callback(lines.append)
        result = runner._run_streaming(
            [sys.executable, "-c", "print('test-sensitive-value'); print('progress', end='')"],
            3,
            True,
        )
        self.assertEqual(lines, ["[redacted]", "progress"])
        self.assertNotIn("test-sensitive-value", result.stdout)

    def test_critical_process_cannot_be_cancelled(self):
        runner = CommandRunner()
        runner._current_process = MagicMock()
        runner._current_process.poll.return_value = None
        runner._cancel_allowed = False
        with patch("sourcedock.core.runner.terminate_process") as terminate:
            self.assertFalse(runner.cancel_current())
        terminate.assert_not_called()

    def test_privileged_password_is_cleared_on_success_and_failure(self):
        for code in (0, 1):
            runner = CommandRunner()
            runner.set_sudo_password("secret")
            with (
                patch.object(runner, "_wait_for_apt_locks"),
                patch.object(
                    runner,
                    "run",
                    side_effect=[
                        subprocess.CompletedProcess([], 1, "", ""),
                        subprocess.CompletedProcess([], code, "", "failure" if code else ""),
                    ],
                ),
            ):
                if code:
                    with self.assertRaises(BackendError):
                        runner.run_privileged(["test-command"])
                else:
                    runner.run_privileged(["test-command"])
            self.assertIsNone(runner._sudo_password)

    def test_application_lookup_never_uses_partial_or_ambiguous_identity(self):
        registry = ApplicationRegistry(runner=MagicMock())
        apps = [
            UnifiedApplication("apt:code", "Code", SOURCE_APT, package_name="code"),
            UnifiedApplication("flatpak:code", "Code", SOURCE_FLATPAK, package_name="code"),
        ]
        snapshot = ApplicationSnapshot(apps)
        self.assertIsNone(registry.find_application("co", snapshot))
        self.assertIsNone(registry.find_application("code", snapshot))
        self.assertIs(registry.find_application("apt:code", snapshot), apps[0])

    def test_cancellation_stops_a_process_that_ignores_sigterm(self):
        runner = CommandRunner()
        ready = threading.Event()
        runner.set_output_callback(lambda _line: ready.set())
        failures = []

        def worker():
            try:
                runner._run_streaming(
                    [
                        sys.executable,
                        "-c",
                        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(20)",
                    ],
                    10,
                    True,
                )
            except BackendError as exc:
                failures.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(ready.wait(2))
        self.assertTrue(runner.cancel_current())
        thread.join(4)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any("cancelled" in failure.lower() for failure in failures))

    def test_source_merge_preserves_independent_installed_packages(self):
        registry = ApplicationRegistry(runner=MagicMock())
        native = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        flatpak = UnifiedApplication(
            "flatpak:editor", "Editor", SOURCE_FLATPAK, package_name="org.example.Editor"
        )
        self.assertEqual(len(registry._merge_applications([native, flatpak])), 2)


if __name__ == "__main__":
    unittest.main()
