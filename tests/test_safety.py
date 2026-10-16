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
from sourcedock.backend.distro import DistroInfo
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
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
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

    def test_shortcut_failure_keeps_the_portable_installation_retryable(self):
        app = self._registered_app()
        item = load_portable_registry()[app.id]
        desktop = self.root / "data" / "applications" / "sourcedock-portable-demo.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text("[Desktop Entry]\nName=Demo\n")
        register_portable_app(
            app.name, "1.0", app.install_path, app.executable, str(desktop),
            managed_root=item["managed_root"],
        )
        provider = PortableProvider(self.runner)
        with patch.object(Path, "unlink", side_effect=PermissionError("shortcut locked")):
            with self.assertRaises(BackendError):
                provider.remove(app)
        self.assertTrue(Path(app.install_path).is_dir())
        self.assertIn(app.id, load_portable_registry())
        provider.remove(app)
        self.assertFalse(Path(app.install_path).exists())
        self.assertFalse(desktop.exists())
        self.assertNotIn(app.id, load_portable_registry())

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


class TestRemovalSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.runner = MagicMock()
        self.runner.command_exists.return_value = True
        self.registry = ApplicationRegistry(
            distro_info=DistroInfo(id="ubuntu", native_manager=SOURCE_APT), runner=self.runner
        )

    def _flatpak_app(self, app_id="org.example.Demo", scope="user"):
        install_root = (
            Path.home() / ".local/share/flatpak/app" if scope == "user" else Path("/var/lib/flatpak/app")
        )
        return UnifiedApplication(
            f"flatpak:{app_id}",
            "Demo",
            SOURCE_FLATPAK,
            package_name=app_id,
            install_path=str(install_root / app_id),
        )

    def test_flatpak_cleanup_without_reviewed_plan_never_calls_provider(self):
        self.runner.reset_mock()
        with self.assertRaisesRegex(BackendError, "Review a Flatpak cleanup plan"):
            self.registry.flatpak_cleanup()
        self.assertEqual(self.runner.mock_calls, [])

    def test_flatpak_cleanup_delegates_only_the_supplied_plan(self):
        from sourcedock.backend.flatpak_cleanup import CleanupRef

        plan = (CleanupRef("user", "runtime/org.example.Platform/x86_64/stable"),)
        self.runner.reset_mock()
        with patch("sourcedock.backend.flatpak_cleanup.apply_cleanup") as apply:
            self.registry.flatpak_cleanup(plan)
        apply.assert_called_once_with(self.runner, plan)
        self.assertEqual(self.runner.mock_calls, [])

    def test_targeted_apt_purge_never_runs_autoremove_or_deletes_user_data(self):
        config = self.home / ".config/demo/settings"
        config.parent.mkdir(parents=True)
        config.write_text("keep")
        app = UnifiedApplication("apt:demo", "Demo", SOURCE_APT, package_name="demo")
        for remove in (
            lambda: self.registry.remove(app, purge=True),
            lambda: self.registry.remove_native_package("demo", purge=True),
        ):
            with self.subTest(remove=remove):
                self.runner.reset_mock()
                remove()
                self.runner.run_privileged.assert_called_once_with(
                    ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "purge", "-y", "demo"],
                    timeout=1800,
                )
                self.runner.run.assert_not_called()
                self.assertEqual(config.read_text(), "keep")

    def test_flatpak_purge_rejects_invalid_ids_before_provider_or_data_removal(self):
        valuable = self.home / "important.txt"
        valuable.write_text("keep")
        for app_id in (
            "",
            "..",
            "../..",
            "../../Documents",
            "/tmp/org.example.Demo",
            "org.example.Demo/../other",
            "org.example.Demo\\..",
            "org..Demo",
            "org.example.",
            "org.Demo",
            "org.ex-ample.Demo",
            "1org.example.Demo",
            "org.example.1Demo",
            "org.example.Demo\n",
            "org.example.Demo\x00",
            "--delete-data",
            "org.example.Demo/x86_64/stable",
            "org.example." + "x" * 244,
            None,
            42,
        ):
            with self.subTest(app_id=app_id):
                self.runner.reset_mock()
                app = UnifiedApplication("flatpak:invalid", "Demo", SOURCE_FLATPAK, package_name=app_id)
                with patch("sourcedock.backend.manager.shutil.rmtree") as remove_data:
                    with self.assertRaisesRegex(BackendError, "Invalid Flatpak application ID"):
                        self.registry.remove(app, purge=True)
                remove_data.assert_not_called()
                self.runner.run.assert_not_called()
                self.runner.run_privileged.assert_not_called()
                self.assertEqual(valuable.read_text(), "keep")

    def test_flatpak_purge_rejects_symlink_ancestry_before_provider_actions(self):
        outside = self.root / "outside"
        outside.mkdir()
        valuable = outside / "important.txt"
        valuable.write_text("keep")
        for index, relative in enumerate((".var", ".var/app", ".var/app/org.example.Demo")):
            with self.subTest(path=relative):
                self.runner.reset_mock()
                home = self.root / f"home-{index}"
                home.mkdir()
                link = home / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(outside, target_is_directory=True)
                with patch.dict(os.environ, {"HOME": str(home)}):
                    with self.assertRaisesRegex(BackendError, "symbolic link"):
                        self.registry.remove(self._flatpak_app(), purge=True)
                self.runner.run.assert_not_called()
                self.runner.run_privileged.assert_not_called()
                self.assertEqual(valuable.read_text(), "keep")

    def test_flatpak_purge_rejects_dangling_symlink_before_provider_actions(self):
        link = self.home / ".var"
        link.symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaisesRegex(BackendError, "symbolic link"):
            self.registry.remove(self._flatpak_app(), purge=True)
        self.runner.run.assert_not_called()
        self.assertTrue(link.is_symlink())

    def test_flatpak_purge_rejects_non_directory_before_provider_actions(self):
        (self.home / ".var").write_text("keep")
        with self.assertRaisesRegex(BackendError, "not a directory"):
            self.registry.remove(self._flatpak_app(), purge=True)
        self.runner.run.assert_not_called()
        self.assertEqual((self.home / ".var").read_text(), "keep")

    def test_flatpak_purge_removes_only_confirmed_app_data_after_uninstall(self):
        for scope in ("user", "system"):
            with self.subTest(scope=scope):
                self.runner.reset_mock()
                app = self._flatpak_app("org.example.My-App", scope)
                data = self.home / ".var/app" / app.package_name
                data.mkdir(parents=True)
                (data / "settings").write_text("remove")
                sibling = data.with_name("org.example.Other")
                sibling.mkdir(exist_ok=True)
                (sibling / "settings").write_text("keep")

                def uninstall(command, **_kwargs):
                    self.assertTrue((data / "settings").exists())
                    return subprocess.CompletedProcess(command, 0, "", "")

                self.runner.run.side_effect = uninstall
                self.registry.remove(app, purge=True)
                self.runner.run.assert_called_once_with(
                    ["flatpak", "uninstall", f"--{scope}", "-y", app.package_name],
                    timeout=1800,
                    check=True,
                )
                self.runner.run_privileged.assert_not_called()
                self.assertFalse(data.exists())
                self.assertEqual((sibling / "settings").read_text(), "keep")

    def test_flatpak_purge_allows_missing_data_without_creating_directories(self):
        app = self._flatpak_app()
        with patch("sourcedock.backend.manager.shutil.rmtree") as remove_data:
            self.registry.remove(app, purge=True)
        self.runner.run.assert_called_once()
        remove_data.assert_not_called()
        self.assertFalse((self.home / ".var").exists())

    def test_flatpak_uninstall_without_purge_preserves_symlinked_data(self):
        outside = self.root / "outside"
        outside.mkdir()
        valuable = outside / "settings"
        valuable.write_text("keep")
        (self.home / ".var").symlink_to(outside, target_is_directory=True)
        with patch("sourcedock.backend.manager.shutil.rmtree") as remove_data:
            self.registry.remove(self._flatpak_app(), purge=False)
        self.runner.run.assert_called_once()
        remove_data.assert_not_called()
        self.assertEqual(valuable.read_text(), "keep")

    def test_failed_flatpak_uninstall_never_removes_data(self):
        data = self.home / ".var/app/org.example.Demo"
        data.mkdir(parents=True)
        valuable = data / "settings"
        valuable.write_text("keep")
        self.runner.run.side_effect = BackendError("uninstall failed")
        with patch("sourcedock.backend.manager.shutil.rmtree") as remove_data:
            with self.assertRaisesRegex(BackendError, "uninstall failed"):
                self.registry.remove(self._flatpak_app(), purge=True)
        remove_data.assert_not_called()
        self.assertEqual(valuable.read_text(), "keep")

    def test_flatpak_data_removal_failure_is_reported_with_path_and_cause(self):
        data = self.home / ".var/app/org.example.Demo"
        data.mkdir(parents=True)
        with patch("sourcedock.backend.manager.shutil.rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(BackendError) as raised:
                self.registry.remove(self._flatpak_app(), purge=True)
        self.runner.run.assert_called_once()
        self.assertIn("uninstalled", str(raised.exception))
        self.assertIn(str(data), str(raised.exception))
        self.assertIn("denied", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, PermissionError)
        self.assertTrue(data.exists())

    def test_flatpak_purge_rechecks_ancestry_after_provider_operation(self):
        apps_dir = self.home / ".var/app"
        data = apps_dir / "org.example.Demo"
        data.mkdir(parents=True)
        (data / "settings").write_text("keep original")
        outside = self.root / "outside"
        redirected = outside / "org.example.Demo"
        redirected.mkdir(parents=True)
        (redirected / "settings").write_text("keep outside")

        def replace_ancestor(command, **_kwargs):
            apps_dir.rename(apps_dir.with_name("saved"))
            apps_dir.symlink_to(outside, target_is_directory=True)
            return subprocess.CompletedProcess(command, 0, "", "")

        self.runner.run.side_effect = replace_ancestor
        with self.assertRaisesRegex(BackendError, "symbolic link"):
            self.registry.remove(self._flatpak_app(), purge=True)
        self.runner.run.assert_called_once()
        self.assertEqual((redirected / "settings").read_text(), "keep outside")
        self.assertEqual(
            (apps_dir.with_name("saved") / "org.example.Demo/settings").read_text(), "keep original"
        )


class TestProcessSafety(unittest.TestCase):
    def test_read_only_provider_queries_do_not_take_the_transaction_lock(self):
        for command in (
            ["apt", "list", "--upgradable"], ["flatpak", "list", "--user"],
            ["snap", "list"], ["snap", "find", "editor"],
            ["flatpak-spawn", "--host", "flatpak", "remote-info", "flathub", "org.example.App"],
            ["apt", "-o", "DPkg::Lock::Timeout=0", "list", "--upgradable"],
            ["pacman", "-Qi", "example"],
        ):
            with self.subTest(command=command):
                self.assertFalse(critical_command(command))
        for command in (
            ["apt", "install", "list"], ["snap", "remove", "list"],
            ["flatpak", "uninstall", "--user", "org.example.App"],
        ):
            with self.subTest(command=command):
                self.assertTrue(critical_command(command))

    def test_streaming_failures_redact_password_in_arguments_and_os_errors(self):
        runner = CommandRunner.__new__(CommandRunner)
        runner._sudo_password = "private-test-value"
        runner._output_callback = None
        for failure in (
            subprocess.CompletedProcess([], 1, "private-test-value", ""),
            OSError("private-test-value"),
        ):
            context = (
                patch("sourcedock.core.runner.stream_process", side_effect=failure)
                if isinstance(failure, Exception)
                else patch("sourcedock.core.runner.stream_process", return_value=failure)
            )
            with self.subTest(failure=type(failure).__name__), context:
                with self.assertRaises(BackendError) as error:
                    runner._run_streaming(["fake", "private-test-value"], 1, True)
                self.assertNotIn("private-test-value", str(error.exception))

    def test_daemon_and_local_package_transactions_are_critical(self):
        for command in (
            ["snap", "install", "demo"], ["sudo", "-S", "rpm", "-U", "demo.rpm"],
            ["flatpak", "install", "--user", "example"], ["AppImageUpdate", "/tmp/example.AppImage"],
        ):
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

    def test_hidden_updates_are_not_provider_failures_or_progressive_notices(self):
        registry = ApplicationRegistry(distro_info=DistroInfo(native_manager=SOURCE_APT), runner=MagicMock())
        registry.native_provider._hidden_upgradable = {"libdemo", "demo-data"}
        errors = ["snap: timeout after 5s"]
        snapshot = registry._build_snapshot([], errors)
        self.assertEqual(snapshot.provider_errors, errors)
        self.assertEqual(len(snapshot.provider_notices), 1)
        self.assertIn("demo-data, libdemo", snapshot.provider_notices[0])
        partial = registry._build_snapshot([], errors, include_hidden=False)
        self.assertEqual(partial.provider_errors, errors)
        self.assertEqual(partial.provider_notices, [])
        self.assertEqual(errors, ["snap: timeout after 5s"])

    def test_apt_lock_wait_can_be_cancelled_responsively(self):
        runner = CommandRunner()
        messages = []
        runner.set_output_callback(messages.append)
        with patch.object(runner, "_apt_lock_holders", return_value=[("9999", "apt-get upgrade")]):
            ready = threading.Event()

            def monitor(msg):
                messages.append(msg)
                ready.set()

            runner.set_output_callback(monitor)
            failures = []

            def worker():
                try:
                    runner._wait_for_apt_locks(["apt", "install", "demo"], max_wait=30)
                except BackendError as exc:
                    failures.append(str(exc))

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(ready.wait(2))
            self.assertTrue(runner.cancel_current())
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(any("cancelled" in f.lower() for f in failures))


if __name__ == "__main__":
    unittest.main()
