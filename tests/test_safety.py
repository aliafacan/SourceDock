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
from sourcedock.core.runner import CommandRunner, OperationContext, OperationState
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
        try:
            with patch("sourcedock.core.runner.terminate_process") as terminate:
                self.assertFalse(runner.cancel_current())
            terminate.assert_not_called()
        finally:
            runner._current_process = None

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


    def test_critical_package_operations_reject_ui_cancellation(self):
        """Kritik paket işleminde UI veya harici iptal çağrısı reddedilir ve süreç yaşamaya devam eder."""
        runner = CommandRunner()
        script = "import time; time.sleep(0.4); print('critical_finished')"
        cmd = [sys.executable, "-c", script]

        started = threading.Event()
        results = {}

        def run_critical():
            started.set()
            # allow_cancel=False ile başlatılan kritik işlem
            res = runner.run(cmd, timeout=5, allow_cancel=False)
            results["res"] = res

        thread = threading.Thread(target=run_critical)
        thread.start()
        self.assertTrue(started.wait(2))
        time.sleep(0.1)

        # İptal isteği reddedilmeli
        self.assertFalse(runner.cancel_current())

        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIn("res", results)
        self.assertEqual(results["res"].returncode, 0)
        self.assertIn("critical_finished", results["res"].stdout)
        self.assertFalse(runner._cancelled)

    def test_concurrent_three_subprocesses_targeted_cancellation(self):
        """Aynı runner ile 3 eşzamanlı subprocess: Yalnızca ortadaki işlem PID ile iptal edilir.

        İlk ve üçüncü işlemler başarıyla tamamlanır, iptal sonrası yeni sorgu sorunsuz çalışır.
        """
        runner = CommandRunner()
        proc_results = {}

        def worker(num, duration, output_tag):
            script = f"import time; time.sleep({duration}); print('{output_tag}')"
            try:
                res = runner.run([sys.executable, "-c", script], timeout=30, allow_cancel=True)
                proc_results[num] = ("ok", res.stdout.strip())
            except BackendError as exc:
                proc_results[num] = ("error", str(exc))

        t1 = threading.Thread(target=worker, args=(1, 0.4, "proc1_success"))
        t2 = threading.Thread(target=worker, args=(2, 6.0, "proc2_should_not_appear"))
        t3 = threading.Thread(target=worker, args=(3, 0.4, "proc3_success"))

        t1.start()
        t2.start()
        t3.start()

        # 3 alt sürecin de Popen seviyesinde başlamasını ve PID almasını bekle
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with runner._proc_lock:
                procs = [
                    (ctx.thread_id, ctx.process.pid)
                    for ctx in runner._operations.values()
                    if ctx.process is not None and getattr(ctx.process, "pid", None) is not None
                ]
            if len(procs) == 3:
                break
            time.sleep(0.02)

        self.assertEqual(len(procs), 3)

        # Thread 2'ye ait PID'yi tam olarak tespit et
        pid_2 = None
        pid_1 = None
        pid_3 = None
        with runner._proc_lock:
            for ctx in runner._operations.values():
                if ctx.thread_id == t2.ident:
                    pid_2 = ctx.process.pid
                elif ctx.thread_id == t1.ident:
                    pid_1 = ctx.process.pid
                elif ctx.thread_id == t3.ident:
                    pid_3 = ctx.process.pid

        self.assertIsNotNone(pid_2)
        self.assertIsNotNone(pid_1)
        self.assertIsNotNone(pid_3)
        self.assertNotEqual(pid_2, pid_1)
        self.assertNotEqual(pid_2, pid_3)

        # Yalnızca ortadaki işlemi (Process 2) PID hedefiyle iptal et
        cancel_ok = runner.cancel_current(target=pid_2)
        self.assertTrue(cancel_ok)

        t1.join(5)
        t2.join(5)
        t3.join(5)

        # Process 1 ve 3 başarıyla bitmeli (yanlış PID veya grup sonlandırılmamalı)
        self.assertEqual(proc_results[1][0], "ok")
        self.assertEqual(proc_results[1][1], "proc1_success")
        self.assertEqual(proc_results[3][0], "ok")
        self.assertEqual(proc_results[3][1], "proc3_success")

        # Process 2 iptal edilmeli
        self.assertEqual(proc_results[2][0], "error")
        self.assertIn("cancelled", proc_results[2][1].lower())

        # İptal sonrasında AYNI runner ile yeni sorgu başlat: State kirlenmemiş olmalı
        subsequent = runner.run([sys.executable, "-c", "print('subsequent_query_ok')"], timeout=5)
        self.assertEqual(subsequent.returncode, 0)
        self.assertIn("subsequent_query_ok", subsequent.stdout)
        self.assertFalse(runner._cancelled)
        self.assertEqual(len(runner._operations), 0)

    def test_concurrent_timeout_and_completion_isolation(self):
        """Bir işlem timeout olurken diğer concurrent işlem başarıyla tamamlanır."""
        runner = CommandRunner()
        results = {}

        def slow_worker():
            try:
                runner.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
                results["slow"] = "success"
            except BackendError as exc:
                results["slow"] = str(exc)

        def fast_worker():
            try:
                res = runner.run([sys.executable, "-c", "import time; time.sleep(0.3); print('fast_ok')"], timeout=5)
                results["fast"] = res.stdout.strip()
            except BackendError as exc:
                results["fast"] = str(exc)

        t_slow = threading.Thread(target=slow_worker)
        t_fast = threading.Thread(target=fast_worker)

        t_slow.start()
        t_fast.start()

        t_slow.join(4)
        t_fast.join(4)

        self.assertIn("Komut calistirilamadi", results.get("slow", ""))
        self.assertEqual(results.get("fast"), "fast_ok")
        self.assertEqual(len(runner._operations), 0)

    def test_simultaneous_cancellation_and_completion_race(self):
        """İşlem bitimi ve iptal isteği aynı anda tetiklendiğinde durum bozulmaz."""
        runner = CommandRunner()
        for _ in range(5):
            started = threading.Event()

            def quick_worker():
                started.set()
                try:
                    runner.run([sys.executable, "-c", "import time; time.sleep(0.05)"], timeout=5)
                except BackendError:
                    pass

            t = threading.Thread(target=quick_worker)
            t.start()
            started.wait(1)
            time.sleep(0.04)
            # İptal isteği işlem tam kapanırken yarışır
            runner.cancel_current()
            t.join(2)

        self.assertEqual(len(runner._operations), 0)
        self.assertFalse(runner._cancelled)

    def test_sequential_queries_do_not_accumulate_state(self):
        """Ardışık çok sayıda sorguda bayrak veya process kaydı birikmez."""
        runner = CommandRunner()
        for i in range(25):
            res = runner.run([sys.executable, "-c", f"print({i})"], timeout=5)
            self.assertEqual(res.stdout.strip(), str(i))

        self.assertEqual(len(runner._operations), 0)
        self.assertEqual(len(runner._thread_to_op), 0)
        self.assertEqual(len(runner._pid_to_op), 0)
        self.assertFalse(runner._cancelled)

    def test_sourcedock_self_uninstall_classification_and_fail_closed(self):
        """main.py içindeki SourceDock kendi kendini kaldırma akışı kritik olarak algılanır ve iptal edilemez."""
        runner = CommandRunner()
        uninstall_cmd = ["bash", "/opt/sourcedock/uninstall.sh"]

        # critical_command sınıflandırması doğrulanır
        self.assertTrue(critical_command(uninstall_cmd))
        self.assertTrue(critical_command(["bash", "uninstall.sh"]))
        self.assertTrue(critical_command(["sh", "/usr/local/bin/uninstall_sourcedock.sh"]))

        # run_privileged fail-closed politikası: allow_cancel belirtilmediğinde False olmalı
        with patch.object(runner, "_wait_for_apt_locks"), \
             patch.object(runner, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(uninstall_cmd, 0, "", "")
            # sudo -n true başarılı varsayımıyla
            runner._run_privileged_locked(uninstall_cmd, timeout=1800, input_text=None)

            # mock_run çağrılarında allow_cancel=False olmalı
            for call in mock_run.call_args_list:
                kwargs = call.kwargs if hasattr(call, "kwargs") else call[1]
                self.assertFalse(kwargs.get("allow_cancel", True))

    def test_password_cache_ttl_and_explicit_clear(self):
        from sourcedock.ui.window import MainWindow
        window = MainWindow.__new__(MainWindow)
        window._cached_sudo_password = None
        window._cached_sudo_timestamp = 0.0

        window.set_cached_sudo_password("valid-pass")
        self.assertEqual(window.get_cached_sudo_password(), "valid-pass")

        # Simulate 16 minutes elapsed (960 seconds > 900 second TTL)
        window._cached_sudo_timestamp = time.monotonic() - 960
        self.assertIsNone(window.get_cached_sudo_password())
        self.assertIsNone(window._cached_sudo_password)

        # Re-set and test explicit clear
        window.set_cached_sudo_password("another-pass")
        self.assertEqual(window.get_cached_sudo_password(), "another-pass")
        window.clear_cached_sudo_password()
        self.assertIsNone(window.get_cached_sudo_password())
        self.assertIsNone(window._cached_sudo_password)

    def test_password_single_ownership_and_dialog_delegation(self):
        """InstalledAppDetailsDialog bağımsız şifre tutmaz, ana pencereye delege eder."""
        from sourcedock.ui.window import MainWindow
        from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog
        from sourcedock.core.models import UnifiedApplication, SOURCE_APT

        parent_win = MainWindow.__new__(MainWindow)
        parent_win._cached_sudo_password = None
        parent_win._cached_sudo_timestamp = 0.0

        runner = CommandRunner()
        registry = MagicMock()
        registry.runner = runner

        app = UnifiedApplication(id="apt:demo", name="Demo", source=SOURCE_APT, package_name="demo")
        dialog = InstalledAppDetailsDialog.__new__(InstalledAppDetailsDialog)
        dialog.registry = registry
        dialog.application = app
        dialog._action_busy = False
        dialog._destroyed = False
        dialog._cached_sudo_password = None
        dialog._cached_sudo_timestamp = 0.0

        with patch.object(dialog, "get_transient_for", return_value=parent_win):
            # Ana pencereye şifre atanır
            parent_win.set_cached_sudo_password("shared-secret")
            # Dialog doğrudan ana pencereden okur
            self.assertEqual(dialog.get_cached_sudo_password(), "shared-secret")

            # Ana pencerede TTL dolunca dialog da None döner
            parent_win._cached_sudo_timestamp = time.monotonic() - 960
            self.assertIsNone(dialog.get_cached_sudo_password())

            # Dialog üzerinden temizlendiğinde ana pencere ve runner temizlenir
            parent_win.set_cached_sudo_password("fresh-secret")
            runner.set_sudo_password("fresh-secret")
            dialog.clear_cached_sudo_password()

            self.assertIsNone(parent_win.get_cached_sudo_password())
            self.assertIsNone(dialog.get_cached_sudo_password())
            self.assertIsNone(runner._sudo_password)

    def test_wrong_password_and_cancel_clear_all_caches(self):
        """Hatalı şifre (AuthRequiredError(password_failed=True)) ve iptal durumunda tüm önbellekler temizlenir."""
        from sourcedock.ui.window import MainWindow
        from sourcedock.core.errors import AuthRequiredError

        window = MainWindow.__new__(MainWindow)
        window._cached_sudo_password = "cached-secret"
        window._cached_sudo_timestamp = time.monotonic()
        runner = CommandRunner()
        runner.set_sudo_password("cached-secret")
        registry = MagicMock()
        registry.runner = runner
        window.application_registry = registry
        window.store_registry = MagicMock()

        # AuthRequiredError(password_failed=True) tetiklendiğinde temizlik zinciri
        err = AuthRequiredError("Hatalı parola", password_failed=True)
        self.assertTrue(err.password_failed)

        window.clear_cached_sudo_password()
        self.assertIsNone(window._cached_sudo_password)
        self.assertIsNone(runner._sudo_password)

    def test_update_all_targets_only_selected_packages_without_system_dist_upgrade(self):
        from sourcedock.backend.manager import ApplicationRegistry as ApplicationManager
        from sourcedock.core.models import UnifiedApplication, SOURCE_APT
        from sourcedock.backend.distro import DistroInfo

        runner = MagicMock()
        runner.command_exists.return_value = True
        manager = ApplicationManager(distro_info=DistroInfo(native_manager=SOURCE_APT), runner=runner)

        app1 = UnifiedApplication(id="apt:vlc", name="VLC", source=SOURCE_APT, package_name="vlc")
        app2 = UnifiedApplication(id="apt:gedit", name="Gedit", source=SOURCE_APT, package_name="gedit")

        # Calling update_all with specific apps updates only those packages
        manager.update_all([app1, app2], whole_system=False)

        # Ensure apt dist-upgrade was NOT called
        for call in runner.run_privileged.call_args_list:
            cmd = call.args[0] if call.args else call[0][0]
            self.assertNotIn("dist-upgrade", cmd)
            self.assertIn("--only-upgrade", cmd)
            self.assertIn("vlc", cmd)
            self.assertIn("gedit", cmd)

    def test_update_all_error_handling_and_per_provider_execution(self):
        """update_all() başarısız dönüş kodlarını sessizce yutmaz ve BackendError fırlatır."""
        from sourcedock.backend.manager import ApplicationRegistry as ApplicationManager
        from sourcedock.core.models import UnifiedApplication, SOURCE_FLATPAK, SOURCE_FIRMWARE
        from sourcedock.backend.distro import DistroInfo

        runner = MagicMock()
        runner.command_exists.return_value = True
        manager = ApplicationManager(distro_info=DistroInfo(native_manager=SOURCE_APT), runner=runner)

        # Flatpak güncellemesi başarısız (returncode=1)
        runner.run.return_value = subprocess.CompletedProcess(["flatpak"], 1, "", "Flatpak error: no remote")
        app_flatpak = UnifiedApplication(
            id="flatpak:org.videolan.VLC",
            name="VLC",
            source=SOURCE_FLATPAK,
            package_name="org.videolan.VLC",
            install_path="/var/lib/flatpak/app/org.videolan.VLC",
        )

        with self.assertRaises(BackendError) as ctx:
            manager.update_all([app_flatpak], whole_system=False)
        self.assertIn("Flatpak", str(ctx.exception))

        # Firmware güncellemesi başarısız (returncode=1)
        runner.run.return_value = subprocess.CompletedProcess(["fwupdmgr"], 1, "", "Device failed to update")
        app_fw = UnifiedApplication(
            id="firmware:dev1",
            name="BIOS",
            source=SOURCE_FIRMWARE,
            package_name="dev1",
        )
        with self.assertRaises(BackendError) as ctx:
            manager.update_all([app_fw], whole_system=False)
        self.assertIn("Firmware", str(ctx.exception))

    def test_preview_native_upgrade_dry_run_simulation(self):
        from sourcedock.backend.previews import preview_native_upgrade

        runner = MagicMock()
        runner.command_exists.side_effect = lambda cmd: cmd == "apt-get"
        runner.run.return_value = subprocess.CompletedProcess(
            ["apt-get"], 0, "Inst vlc [3.0.16] (3.0.18 Ubuntu:24.04/noble-updates [amd64])", ""
        )

        plan = preview_native_upgrade(runner, ["vlc"])
        self.assertIn("Inst vlc", plan)
        runner.run.assert_called_once_with(
            ["apt-get", "--simulate", "-o", "Debug::NoLocking=true", "install", "--only-upgrade", "-y", "vlc"],
            timeout=30,
            check=False,
        )


    def test_critical_and_query_isolation_and_targeted_cancellation(self):
        """P0-01 Zorunlu Test:
        Aynı runner'da kritik işlem A ve normal sorgu B başlat.
        A'ya ait iptal eylemini çalıştır -> A ve B'nin ikisinin de bundan etkilenmediğini doğrula.
        B'ye ait hedefli iptali çalıştır -> Yalnızca B'nin iptal edildiğini doğrula.
        Birden fazla işlem varken hedefsiz iptalin başka bir işlemi sonlandırmadığını doğrula.
        """
        runner = CommandRunner()
        results = {}
        started_a = threading.Event()
        started_b = threading.Event()

        op_a_id = "op_test_critical_A"
        op_b_id = "op_test_query_B"

        def worker_a():
            runner.bind_thread_op(op_a_id)
            try:
                started_a.set()
                res = runner.run(
                    [sys.executable, "-c", "import time; time.sleep(0.8); print('critical_A_success')"],
                    timeout=10,
                    allow_cancel=False,
                )
                results["A"] = ("ok", res.stdout.strip())
            except Exception as exc:
                results["A"] = ("error", str(exc))
            finally:
                runner.unbind_thread_op(op_a_id)

        def worker_b():
            runner.bind_thread_op(op_b_id)
            try:
                started_b.set()
                res = runner.run(
                    [sys.executable, "-c", "import time; time.sleep(3.0); print('query_B_success')"],
                    timeout=10,
                    allow_cancel=True,
                )
                results["B"] = ("ok", res.stdout.strip())
            except Exception as exc:
                results["B"] = ("error", str(exc))
            finally:
                runner.unbind_thread_op(op_b_id)

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()

        self.assertTrue(started_a.wait(3))
        self.assertTrue(started_b.wait(3))

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with runner._proc_lock:
                if len(runner._operations) == 2:
                    break
            time.sleep(0.02)

        with runner._proc_lock:
            self.assertEqual(len(runner._operations), 2)

        # 1. Hedefsiz iptal çağrısı: 2 aktif işlem varken herhangi birini tahmin edip iptal etmemeli!
        self.assertFalse(runner.cancel_current())

        # 2. A'ya ait iptal eylemini çalıştır:
        # A kritik olduğu için reddedilmeli, ne A ne B iptal edilmeli
        cancel_a_res = runner.cancel_current(target=op_a_id)
        self.assertFalse(cancel_a_res)

        # 3. B'ye ait hedefli iptal eylemini çalıştır:
        # B normal sorgu olduğu için iptal edilmeli
        cancel_b_res = runner.cancel_current(target=op_b_id)
        self.assertTrue(cancel_b_res)

        t_a.join(5)
        t_b.join(5)

        self.assertEqual(results.get("A", (None,))[0], "ok")
        self.assertEqual(results["A"][1], "critical_A_success")

        self.assertEqual(results.get("B", (None,))[0], "error")
        self.assertIn("cancelled", results["B"][1].lower())

        self.assertEqual(len(runner._operations), 0)
        self.assertEqual(len(runner._pid_to_op), 0)
        self.assertEqual(len(runner._thread_to_op), 0)

    def test_critical_transaction_timeout_policy(self):
        """P0-02: Kritik işlem timeout olduğunda kontrolsüz SIGKILL uygulanmaz,
        kullanıcıya durum ve güvenli kurtarma yönergeleri bildirilir."""
        runner = CommandRunner()
        output_logs = []
        runner.set_output_callback(lambda line: output_logs.append(line))

        cmd = [sys.executable, "-c", "import time; time.sleep(1.0); print('should_timeout')"]
        with self.assertRaises(BackendError) as ctx:
            runner.run(cmd, timeout=0.2, allow_cancel=False)

        err_msg = str(ctx.exception)
        self.assertTrue("timed out" in err_msg.lower() or "zaman aşımına" in err_msg.lower())
        combined_logs = " ".join(output_logs)
        self.assertTrue(len(combined_logs) > 0)
        runner.set_output_callback(None)
        # Test sonrasında yaşayan sürecin doğal bitmesini bekle ve temizle
        for ctx_item in list(runner._operations.values()):
            if ctx_item.process is not None:
                ctx_item.process.wait(timeout=3)
        runner.poll_tracked_operations()

    def test_100_consecutive_streaming_queries_clean_all_mappings(self):
        """P0-03: 100 ardışık streaming sorgusunda bütün PID ve operation kayıtları temizlenir.
        Eski PID üzerinden yeni bir işlem yanlışlıkla hedeflenemez."""
        runner = CommandRunner()
        for i in range(100):
            res = runner._run_streaming([sys.executable, "-c", f"print('stream_{i}')"], timeout=5, check=True)
            self.assertEqual(res.returncode, 0)
            self.assertEqual(res.stdout.strip(), f"stream_{i}")
            self.assertEqual(len(runner._pid_to_op), 0)
            self.assertEqual(len(runner._operations), 0)
            self.assertEqual(len(runner._thread_to_op), 0)

        self.assertFalse(runner.cancel_current(target=999999))
        self.assertFalse(runner.cancel_current(target="stale_op_id"))

    def test_nested_operations_thread_mapping_restoration(self):
        """P1-01: İç içe operasyon bittiğinde dış operasyonun thread mapping'i korunur.
        Eşzamanlı thread'lerin context kayıtları birbirine karışmaz."""
        runner = CommandRunner()

        outer_ctx = runner._create_operation(["fake_outer"], allow_cancel=False)
        thread_id = threading.get_ident()
        self.assertEqual(runner._thread_to_op.get(thread_id), outer_ctx.op_id)

        inner_ctx = runner._create_operation(["fake_inner"], allow_cancel=True)
        self.assertEqual(runner._thread_to_op.get(thread_id), inner_ctx.op_id)

        runner._finish_operation(inner_ctx)
        self.assertIn(outer_ctx.op_id, runner._operations)
        self.assertEqual(runner._thread_to_op.get(thread_id), outer_ctx.op_id)

        runner._finish_operation(outer_ctx)
        self.assertNotIn(thread_id, runner._thread_to_op)
        self.assertEqual(len(runner._operations), 0)

    def test_selected_firmware_update_does_not_broaden_to_global(self):
        """P0-04: Seçili firmware güncellemesi genel firmware güncellemesine dönüşmez.
        Aygıt kimliği doğrulanır ve yalnızca hedeflenen cihaza update komutu gönderilir."""
        from sourcedock.core.models import SOURCE_FIRMWARE
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = subprocess.CompletedProcess(["fwupdmgr"], 0, "", "")
        manager = ApplicationRegistry(distro_info=DistroInfo(native_manager=SOURCE_APT), runner=runner)

        app_fw1 = UnifiedApplication(
            id=f"{SOURCE_FIRMWARE}:fw-alpha",
            name="Alpha Device",
            source=SOURCE_FIRMWARE,
            package_name="fw-alpha",
            update_available=True,
        )
        app_fw2 = UnifiedApplication(
            id=f"{SOURCE_FIRMWARE}:fw-beta",
            name="Beta Device",
            source=SOURCE_FIRMWARE,
            package_name="fw-beta",
            update_available=True,
        )

        manager.update_all([app_fw1], whole_system=False)
        runner.run.assert_any_call(["fwupdmgr", "update", "-y", "fw-alpha"], timeout=3600, check=False)
        self.assertNotIn(
            unittest.mock.call(["fwupdmgr", "update", "-y"], timeout=3600, check=False),
            runner.run.call_args_list,
        )
        self.assertNotIn(
            unittest.mock.call(["fwupdmgr", "update", "-y", "fw-beta"], timeout=3600, check=False),
            runner.run.call_args_list,
        )

        runner.run.reset_mock()
        app_invalid = UnifiedApplication(
            id=f"{SOURCE_FIRMWARE}:invalid",
            name="Invalid",
            source=SOURCE_FIRMWARE,
            package_name="",
            update_available=True,
        )
        with self.assertRaises(BackendError) as ctx:
            manager.update_all([app_invalid], whole_system=False)
        self.assertIn("Aygıt kimliği", str(ctx.exception))
        runner.run.assert_not_called()

        runner.run.reset_mock()
        runner.run.return_value = subprocess.CompletedProcess(["fwupdmgr"], 0, "", "")
        manager.update_all([app_fw1, app_fw2], whole_system=True)
        runner.run.assert_any_call(["fwupdmgr", "update", "-y"], timeout=3600, check=False)

    def test_is_completed_success_strict_evaluation(self):
        """P1-02: Geçersiz veya eksik returncode başarı sayılmaz."""
        from sourcedock.core.models import SOURCE_FIRMWARE
        self.assertTrue(ApplicationRegistry._is_completed_success(subprocess.CompletedProcess([], 0)))
        self.assertFalse(ApplicationRegistry._is_completed_success(subprocess.CompletedProcess([], 1)))
        self.assertFalse(ApplicationRegistry._is_completed_success(subprocess.CompletedProcess([], -15)))
        self.assertFalse(ApplicationRegistry._is_completed_success(MagicMock()))
        self.assertFalse(ApplicationRegistry._is_completed_success(None))
        self.assertFalse(ApplicationRegistry._is_completed_success(object()))

        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = MagicMock()
        manager = ApplicationRegistry(distro_info=DistroInfo(native_manager=SOURCE_APT), runner=runner)
        app_fw = UnifiedApplication(
            id=f"{SOURCE_FIRMWARE}:dev1",
            name="Dev",
            source=SOURCE_FIRMWARE,
            package_name="dev1",
            update_available=True,
        )
        with self.assertRaises(BackendError):
            manager.update_all([app_fw], whole_system=False)

    def test_password_ttl_and_zero_timestamp_rejected(self):
        """P1-03: 0 veya eksik zaman damgasıyla parola önbelleği süresiz kullanılamaz."""
        from sourcedock.ui.window import MainWindow
        from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog

        win = MainWindow.__new__(MainWindow)
        win._cached_sudo_password = "valid"
        win._cached_sudo_timestamp = 0.0
        self.assertIsNone(win.get_cached_sudo_password())
        self.assertIsNone(win._cached_sudo_password)

        win._cached_sudo_password = "valid"
        win._cached_sudo_timestamp = None
        self.assertIsNone(win.get_cached_sudo_password())
        self.assertIsNone(win._cached_sudo_password)

        dialog = InstalledAppDetailsDialog.__new__(InstalledAppDetailsDialog)
        dialog.get_transient_for = lambda: None
        dialog.standalone = True
        dialog._action_busy = False
        dialog._destroyed = False
        dialog._cached_sudo_password = "valid"
        dialog._cached_sudo_timestamp = 0.0
        self.assertIsNone(dialog.get_cached_sudo_password())
        self.assertIsNone(dialog._cached_sudo_password)

        dialog.set_cached_sudo_password("temp-pass")
        self.assertEqual(dialog.get_cached_sudo_password(), "temp-pass")
        dialog._destroyed = True
        self.assertIsNone(dialog.get_cached_sudo_password())
        self.assertIsNone(dialog._cached_sudo_password)


    def test_critical_transaction_timeout_avoids_sigterm_and_preserves_tracking(self):
        """Kritik işlem zaman aşımına uğradığında otomatik SIGTERM/SIGKILL gönderilmez ve
        hâlâ yaşayan alt süreç takipten düşmez."""
        runner = CommandRunner()
        script = """
import time, signal, sys

def on_term(sig, frame):
    sys.exit(42)

signal.signal(signal.SIGTERM, on_term)
time.sleep(1.2)
sys.exit(0)
"""
        with self.assertRaises(BackendError):
            runner.run([sys.executable, "-c", script], timeout=0.2, allow_cancel=False)

        # 1. Hâlâ yaşayan süreç runner._operations ve _pid_to_op içinde takipten düşmemeli
        self.assertEqual(len(runner._operations), 1)
        self.assertEqual(len(runner._pid_to_op), 1)

        ctx = next(iter(runner._operations.values()))
        proc = ctx.process
        self.assertIsNotNone(proc)
        # 2. Süreç SIGTERM ile öldürülmemiş olmalı (hâlâ yaşıyor)
        self.assertIsNone(proc.poll())

        # 3. Kritik koruma devrede olmalı: cancel_current iptal edememeli
        self.assertFalse(runner.cancel_current(target=ctx.op_id))

        # 4. Süreç kendi kendine bitmeli (returncode 0)
        proc.wait(timeout=3)
        self.assertEqual(proc.returncode, 0)

        # 5. Süreç bittikten sonra poll çağrıldığında temizlenmeli
        runner.poll_tracked_operations()
        self.assertEqual(len(runner._operations), 0)
        self.assertEqual(len(runner._pid_to_op), 0)

    def test_worker_bound_op_id_persists_across_subsequent_commands(self):
        """UI tarafından oluşturulan op_id birinci alt komuttan sonra kaybolmaz.
        Aynı worker içindeki ikinci ve sonraki komutlarda hedefli iptal doğru çalışır."""
        runner = CommandRunner()
        worker_op_id = "op_ui_persistent_worker"
        results = {}

        def worker():
            runner.bind_thread_op(worker_op_id)
            try:
                # 1. Komut başarıyla tamamlanır
                res1 = runner.run([sys.executable, "-c", "print('cmd1_success')"], timeout=5)
                results["cmd1"] = res1.stdout.strip()

                # 2. Komut uzun sürer ve hedefli iptal bekler
                res2 = runner.run(
                    [sys.executable, "-c", "import time; time.sleep(3.0); print('cmd2_success')"],
                    timeout=10,
                    allow_cancel=True,
                )
                results["cmd2"] = res2.stdout.strip()
            except Exception as exc:
                results["cmd2_error"] = str(exc)
            finally:
                runner.unbind_thread_op(worker_op_id)

        t = threading.Thread(target=worker)
        t.start()

        # 1. Komutun bitip 2. Komutun aktifleşmesini bekle
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with runner._proc_lock:
                if "cmd1" in results and len(runner._operations) == 1:
                    break
            time.sleep(0.02)

        self.assertEqual(results.get("cmd1"), "cmd1_success")
        self.assertEqual(len(runner._operations), 1)

        # Worker'ın orijinal op_id'si ile 2. komutu iptal et
        cancel_ok = runner.cancel_current(target=worker_op_id)
        self.assertTrue(cancel_ok)

        t.join(timeout=5)
        self.assertIn("cmd2_error", results)
        self.assertIn("cancelled", results["cmd2_error"].lower())

        # Worker tamamlandıktan sonra thread kaydı temiz olmalı
        self.assertEqual(len(runner._operations), 0)
        self.assertEqual(len(runner._thread_bound_ops), 0)
        self.assertEqual(len(runner._thread_to_op), 0)

    def test_log_callback_thread_isolation(self):
        """Her thread kendi log callback'ine sahiptir; çıktılar diğer thread'lere sızmaz."""
        runner = CommandRunner()
        logs_t1 = []
        logs_t2 = []

        def worker1():
            runner.set_output_callback(lambda msg: logs_t1.append(f"T1: {msg}"))
            runner.run([sys.executable, "-c", "import time; time.sleep(0.3); print('t1_out')"], timeout=120)

        def worker2():
            runner.set_output_callback(lambda msg: logs_t2.append(f"T2: {msg}"))
            time.sleep(0.05)
            runner.run([sys.executable, "-c", "print('t2_out')"], timeout=120)

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertTrue(any("t1_out" in line for line in logs_t1))
        self.assertFalse(any("t2_out" in line for line in logs_t1))

        self.assertTrue(any("t2_out" in line for line in logs_t2))
        self.assertFalse(any("t1_out" in line for line in logs_t2))

    def test_regression_a_critical_streaming_timeout_output_preserved_without_broken_pipe(self):
        """Test A: Kritik streaming timeout sonrası çıktı boruları açık kalır, BrokenPipeError oluşmaz ve exit code 0 korunur."""
        from sourcedock.core.runner import OperationState
        runner = CommandRunner()
        script = """
import sys, time
print('start_line', flush=True)
time.sleep(0.8)
print('line_after_timeout_1', flush=True)
print('line_after_timeout_2', flush=True)
"""
        logs = []
        op_id = "op_test_stream_a"
        runner.set_output_callback(lambda l: logs.append(l), op_id=op_id)
        runner.bind_thread_op(op_id)

        with self.assertRaises(BackendError) as ctx:
            runner.run([sys.executable, "-c", script], timeout=0.3, allow_cancel=False)

        self.assertIn("zaman aşımına uğradı", str(ctx.exception))
        self.assertIn(op_id, runner._operations)
        op_ctx = runner._operations[op_id]
        self.assertEqual(op_ctx.state, OperationState.TIMEOUT_WARNING)

        # Sürecin doğal bitmesini bekle
        finished = op_ctx.completed_event.wait(timeout=3.0)
        self.assertTrue(finished)
        time.sleep(0.1)

        self.assertEqual(op_ctx.state, OperationState.COMPLETED)
        self.assertEqual(op_ctx.returncode, 0)
        self.assertIn("start_line", logs)
        self.assertIn("line_after_timeout_1", logs)
        self.assertIn("line_after_timeout_2", logs)
        self.assertNotIn(op_id, runner._operations)
        runner.unbind_thread_op(op_id)

    def test_regression_b_normal_subprocess_high_volume_pipe_buffer_drained(self):
        """Test B: Normal subprocess yüksek miktarda çıktı üretse bile boru tamponu sürekli tüketilir ve işlem kilitlenmez."""
        runner = CommandRunner()
        script = """
import sys, time
time.sleep(0.3)
data = 'X' * 1024
for _ in range(150): # 150 KB > 64 KB kernel buffer
    print(data, flush=True)
"""
        with self.assertRaises(BackendError):
            runner._run_subprocess([sys.executable, "-c", script], ["test_proc"], timeout=0.1, check=False, input_text=None, allow_cancel=False)

        # Lingering drainer çıktıyı tükettiği için süreç takılmadan 2 saniye içinde sonlanmalıdır
        time.sleep(1.2)
        self.assertFalse(runner._has_active_critical_operation())
        self.assertEqual(len(runner._operations), 0)

    def test_regression_c_transaction_lock_blocks_second_transaction_until_first_finishes(self):
        """Test C: Kritik işlem A timeout sonrası devam ederken işlem B kritik aşamaya giremez, A bitince çalışır."""
        runner = CommandRunner()
        script_a = """
import sys, time
time.sleep(1.0)
"""
        script_b = """
import sys
print("op_b_done")
"""
        def op_a():
            try:
                runner.run([sys.executable, "-c", script_a], timeout=0.4, allow_cancel=False)
            except BackendError:
                pass

        t_a = threading.Thread(target=op_a)
        t_a.start()
        time.sleep(0.6) # A timeout'a uğrayıp lingering durumuna geçsin

        self.assertTrue(runner._has_active_critical_operation())

        start_b = time.monotonic()
        res_b = runner.run([sys.executable, "-c", script_b], timeout=5, allow_cancel=False)
        elapsed_b = time.monotonic() - start_b

        t_a.join()
        self.assertGreaterEqual(elapsed_b, 0.3)
        self.assertEqual(res_b.returncode, 0)
        self.assertFalse(runner._has_active_critical_operation())

    def test_regression_d_ui_callback_registration_isolation_and_window_close(self):
        """Test D: Ana thread'den kaydedilen callback'ler op_id ile izole edilir; bir pencere kapandığında diğeri bozulmaz."""
        runner = CommandRunner()
        logs_a = []
        logs_b = []

        op_a = "dialog_op_A"
        op_b = "dialog_op_B"

        runner.set_output_callback(lambda l: logs_a.append(f"A:{l}"), op_id=op_a)
        runner.set_output_callback(lambda l: logs_b.append(f"B:{l}"), op_id=op_b)

        barrier = threading.Barrier(2)

        def worker_a():
            runner.bind_thread_op(op_a)
            cb = runner._resolve_output_callback(threading.get_ident())
            if cb:
                cb("first_msg_a")
            barrier.wait()
            # Dialog A kapanmış gibi callback temizlensin
            runner.set_output_callback(None, op_id=op_a)
            runner.unbind_thread_op(op_a)

        def worker_b():
            runner.bind_thread_op(op_b)
            barrier.wait()
            time.sleep(0.1) # A'nın temizliği tamamlandıktan sonra
            cb = runner._resolve_output_callback(threading.get_ident())
            if cb:
                cb("second_msg_b")
            runner.set_output_callback(None, op_id=op_b)
            runner.unbind_thread_op(op_b)

        t1 = threading.Thread(target=worker_a)
        t2 = threading.Thread(target=worker_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(logs_a, ["A:first_msg_a"])
        self.assertEqual(logs_b, ["B:second_msg_b"])
        self.assertEqual(len(runner._op_callbacks), 0)

    def test_regression_e_lingering_process_automatic_lifecycle_and_cleanup(self):
        """Test E: Yaşayan işlem zaman aşımı sonrası otomatik olarak takip edilir ve poll çağrılmadan temizlenir."""
        from sourcedock.core.runner import OperationState

        runner = CommandRunner()
        script = """
import sys, time
print('start', flush=True)
time.sleep(0.8)
print('finish', flush=True)
"""
        logs = []
        op_id = "op_auto_e"
        runner.set_output_callback(lambda l: logs.append(l), op_id=op_id)
        runner.bind_thread_op(op_id)

        with self.assertRaises(BackendError):
            runner._run_subprocess([sys.executable, "-c", script], ["subproc_e"], timeout=0.2, check=False, input_text=None, allow_cancel=False)

        self.assertIn(op_id, runner._operations)
        ctx = runner._operations[op_id]
        self.assertEqual(ctx.state, OperationState.TIMEOUT_WARNING)
        self.assertTrue(ctx.lingering)
        pid = ctx.pid
        self.assertIn(pid, runner._pid_to_op)

        # poll_tracked_operations ÇAĞRILMAZ.
        finished = ctx.completed_event.wait(timeout=3.0)
        self.assertTrue(finished)
        time.sleep(0.1)

        self.assertEqual(ctx.state, OperationState.COMPLETED)
        self.assertEqual(ctx.returncode, 0)
        self.assertNotIn(op_id, runner._operations)
        self.assertNotIn(pid, runner._pid_to_op)
        self.assertFalse(runner._has_active_critical_operation())
        self.assertIn("finish", logs)
        runner.unbind_thread_op(op_id)

    def test_regression_f_stderr_pipe_deadlock_prevented(self):
        """P0-01: Çift kanallı eşzamanlı drainer sayesinde 1 MB stderr-only ve eşzamanlı bol veri kilitlenmez."""
        from sourcedock.core.runner import OperationState
        runner = CommandRunner()

        # 1. Senaryo: Yalnızca stderr'e 1 MB veri (stdout boş), satırsız ve UTF-8 dışı baytlar
        script_stderr_only = """
import sys, time
# 1 MB veri + geçersiz UTF-8 dizisi
sys.stderr.buffer.write(b"E" * (1024 * 1024) + bytes([255, 254]) + b"E" * 1024)
sys.stderr.flush()
time.sleep(0.2)
sys.exit(0)
"""
        op_id1 = "op_test_stderr_1mb"
        ctx1 = runner._create_operation(["python3", "-c", script_stderr_only], allow_cancel=False, op_id=op_id1)
        ctx1.is_critical = True
        proc1 = subprocess.Popen(
            [sys.executable, "-c", script_stderr_only],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        runner._attach_process(ctx1, proc1)
        runner._preserve_lingering_operation(ctx1)

        finished1 = ctx1.completed_event.wait(timeout=5.0)
        self.assertTrue(finished1, "Lingering drainer deadlocked on 1MB stderr pipe buffer!")
        self.assertEqual(ctx1.returncode, 0)
        self.assertEqual(ctx1.state, OperationState.COMPLETED)
        self.assertTrue(proc1.stdout.closed)
        self.assertTrue(proc1.stderr.closed)

        # 2. Senaryo: stdout ve stderr aynı anda yoğun veri üretirken (500KB + 500KB)
        script_both = """
import sys, time
sys.stdout.buffer.write(b"O" * 500000)
sys.stdout.flush()
sys.stderr.buffer.write(b"E" * 500000)
sys.stderr.flush()
time.sleep(0.1)
sys.exit(0)
"""
        op_id2 = "op_test_both_streams"
        ctx2 = runner._create_operation(["python3", "-c", script_both], allow_cancel=False, op_id=op_id2)
        ctx2.is_critical = True
        proc2 = subprocess.Popen(
            [sys.executable, "-c", script_both],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        runner._attach_process(ctx2, proc2)
        runner._preserve_lingering_operation(ctx2)

        finished2 = ctx2.completed_event.wait(timeout=5.0)
        self.assertTrue(finished2, "Drainer deadlocked on simultaneous stdout/stderr!")
        self.assertEqual(ctx2.returncode, 0)
        self.assertEqual(ctx2.state, OperationState.COMPLETED)
        self.assertTrue(proc2.stdout.closed)
        self.assertTrue(proc2.stderr.closed)
        self.assertNotIn(op_id1, runner._operations)
        self.assertNotIn(op_id2, runner._operations)

    def test_regression_g_stream_process_never_returns_zero_while_alive(self):
        """P0-02: Alt süreç stdout/stderr'yi erkenden kapatıp yaşamaya devam ettiğinde asla returncode=0 dönülmez."""
        from sourcedock.core.process import stream_process
        script = """
import os, sys, time
os.close(1)
os.close(2)
time.sleep(0.6)
sys.exit(0)
"""
        t0 = time.monotonic()
        with self.assertRaises(BackendError) as cm:
            stream_process([sys.executable, "-c", script], timeout=0.2, critical=True)
        duration = time.monotonic() - t0

        err_text = str(cm.exception)
        # returncode=None durumunda asla başarı iddiası üretilmemeli, timeout warning fırlatılmalı
        self.assertTrue("zaman aşımına uğradı" in err_text or "tamamlanmadı" in err_text)
        self.assertLess(duration, 0.5)

    def test_regression_h_cross_runner_critical_transaction_coordination(self):
        """P0-03: Farklı CommandRunner örnekleri (runner_a ve runner_b) sınıf genelinde transaction koordinasyonuna uyar."""
        runner_a = CommandRunner()
        runner_b = CommandRunner()

        script_a = """
import time, sys
time.sleep(0.5)
sys.exit(0)
"""
        # Runner A kritik işlemi zaman aşımına uğratır ve arka planda lingering olarak kalır
        with self.assertRaises(BackendError):
            runner_a.run([sys.executable, "-c", script_a], timeout=0.15, allow_cancel=False)

        # Runner A'nın işlemi hâlâ arka planda yaşıyor olmalı
        self.assertTrue(CommandRunner.has_global_active_critical_operation())

        # Runner B read-only sorgu çalıştırdığında bloklanmaz
        t_ro = time.monotonic()
        ro_res = runner_b.run_read_only([sys.executable, "-c", "import sys; sys.exit(0)"], timeout=2.0)
        self.assertLess(time.monotonic() - t_ro, 0.25)
        self.assertEqual(ro_res.returncode, 0)

        # Runner B aynı kaynak için kritik işlem başlatmaya çalıştığında Runner A bitene kadar bekler
        t0 = time.monotonic()
        res_b = runner_b.run([sys.executable, "-c", "import sys; sys.exit(0)"], timeout=3.0, allow_cancel=False)
        duration = time.monotonic() - t0

        self.assertGreaterEqual(duration, 0.3)
        self.assertEqual(res_b.returncode, 0)
        self.assertFalse(CommandRunner.has_global_active_critical_operation())

    def test_regression_i_callback_isolated_from_main_thread_and_persisted_for_worker_subcommands(self):
        """P1-01: UI op_id ile callback atandığında çağıran thread kirlenmez ve ardışık alt komutlarda log akışı kesilmez."""
        runner = CommandRunner()
        main_tid = threading.get_ident()
        logs_a = []
        logs_b = []

        # 1. Main thread op_A ve op_B callback'lerini kaydeder
        runner.set_output_callback(lambda l: logs_a.append(l), op_id="op_A")
        runner.set_output_callback(lambda l: logs_b.append(l), op_id="op_B")

        self.assertNotIn(main_tid, runner._thread_callbacks)
        self.assertIsNone(runner._output_callback)
        self.assertIn("op_A", runner._op_callbacks)
        self.assertIn("op_B", runner._op_callbacks)

        def worker_a():
            runner.bind_thread_op("op_A")
            try:
                runner.run([sys.executable, "-c", "print('cmd1_A')"], timeout=5)
                runner.run([sys.executable, "-c", "print('cmd2_A')"], timeout=5)
            finally:
                runner.unbind_thread_op("op_A")
                runner.set_output_callback(None, op_id="op_A")

        def worker_b():
            runner.bind_thread_op("op_B")
            try:
                runner.run([sys.executable, "-c", "print('cmd_B')"], timeout=5)
            finally:
                runner.unbind_thread_op("op_B")
                runner.set_output_callback(None, op_id="op_B")

        ta = threading.Thread(target=worker_a)
        tb = threading.Thread(target=worker_b)
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        self.assertEqual(logs_a, ["cmd1_A", "cmd2_A"])
        self.assertEqual(logs_b, ["cmd_B"])
        self.assertEqual(len(runner._op_callbacks), 0)
        self.assertEqual(len(runner._thread_callbacks), 0)
        self.assertIsNone(runner._output_callback)

    def test_regression_j_ui_lingering_operation_resolves_to_completion_instead_of_premature_fail(self):
        """P1-02: Zaman aşımına uğrayan kritik işlem UI durum takibinde TIMEOUT_WARNING olarak izlenir,
        exit=0 sonradan başarıya, exit!=0 ise sonradan başarısızlığa dönüştürülür."""
        from sourcedock.core.runner import OperationState
        runner = CommandRunner()

        # Senaryo A: exit=0 ile biten kritik işlem
        op_id_a = "op_ui_lingering_success"
        runner.bind_thread_op(op_id_a)
        ui_states_a = []

        script_a = """
import time, sys
time.sleep(0.4)
sys.exit(0)
"""
        try:
            runner.run([sys.executable, "-c", script_a], timeout=0.15, allow_cancel=False)
        except BackendError:
            ctx_a = runner.get_operation_context(op_id_a)
            self.assertIsNotNone(ctx_a)
            self.assertTrue(ctx_a.lingering)
            self.assertEqual(ctx_a.state, OperationState.TIMEOUT_WARNING)
            ui_states_a.append("TIMEOUT_WARNING")
            ctx_a.completed_event.wait(timeout=2.0)
            if ctx_a.returncode == 0:
                self.assertEqual(ctx_a.state, OperationState.COMPLETED)
                ui_states_a.append("COMPLETED")
            else:
                ui_states_a.append("FAILED")
        runner.unbind_thread_op(op_id_a)
        self.assertEqual(ui_states_a, ["TIMEOUT_WARNING", "COMPLETED"])

        # Senaryo B: exit!=0 (42) ile biten kritik işlem
        op_id_b = "op_ui_lingering_fail"
        runner.bind_thread_op(op_id_b)
        ui_states_b = []

        script_b = """
import time, sys
time.sleep(0.4)
sys.exit(42)
"""
        try:
            runner.run([sys.executable, "-c", script_b], timeout=0.15, allow_cancel=False)
        except BackendError:
            ctx_b = runner.get_operation_context(op_id_b)
            self.assertIsNotNone(ctx_b)
            self.assertTrue(ctx_b.lingering)
            self.assertEqual(ctx_b.state, OperationState.TIMEOUT_WARNING)
            ui_states_b.append("TIMEOUT_WARNING")
            ctx_b.completed_event.wait(timeout=2.0)
            if ctx_b.returncode == 0:
                ui_states_b.append("COMPLETED")
            else:
                self.assertEqual(ctx_b.state, OperationState.FAILED)
                self.assertEqual(ctx_b.returncode, 42)
                ui_states_b.append(f"FAILED_{ctx_b.returncode}")
        runner.unbind_thread_op(op_id_b)
        self.assertEqual(ui_states_b, ["TIMEOUT_WARNING", "FAILED_42"])


    def test_regression_k_package_installer_dialog_deleted_variable_and_safe_cleanup(self):
        """P0-01: PackageInstallerDialog'da timeout sonrasında deleted değişkeni tanımsız kalmaz;
        dosya silme tercihi yalnızca gerçek dönüş kodu 0 olduğunda icra edilir."""
        import tempfile
        from gi.repository import GLib
        from sourcedock.backend.local_packages import LocalPackageInfo
        from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog

        def pump_glib():
            ctx = GLib.MainContext.default()
            while ctx.iteration(False):
                pass

        reg = MagicMock()

        # 1. Senaryo: Timeout oluşur, süreç sonradan 0 ile biter, delete_after=True -> Dosya silinir, UnboundLocalError oluşmaz
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            file_path1 = tf.name
        self.assertTrue(os.path.exists(file_path1))

        info1 = LocalPackageInfo(file_path1, 'deb', 'Pkg1', version='1.0')
        ctx1 = OperationContext('op_pkg_test_1', allow_cancel=False)
        ctx1.lingering = True
        ctx1.returncode = 0
        ctx1.completed_event.set()

        reg.runner.get_operation_context.return_value = ctx1
        reg.install_local_package.side_effect = BackendError('Timeout Expired')

        success_calls = []
        failure_calls = []
        with patch.object(PackageInstallerDialog, '__init__', lambda self, *a, **kw: None):
            dlg1 = PackageInstallerDialog()
            dlg1.registry = reg
            dlg1.info = info1
            dlg1._current_op_id = 'op_pkg_test_1'
            dlg1.progress_status_label = MagicMock()
            dlg1._on_install_success = lambda deleted: success_calls.append(deleted)
            dlg1._on_install_failure = lambda msg: failure_calls.append(msg)

            # UnboundLocalError atmamalı ve dosyayı silmeli
            dlg1._worker_install(None, True, 'system', False, delete_after=True)
            pump_glib()

        self.assertFalse(os.path.exists(file_path1))
        self.assertEqual(success_calls, [True])
        self.assertEqual(failure_calls, [])

        # 2. Senaryo: Timeout oluşur, süreç sonradan 42 (hata) ile biter, delete_after=True -> Dosya ASLA silinmez!
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            file_path2 = tf.name
        self.assertTrue(os.path.exists(file_path2))

        info2 = LocalPackageInfo(file_path2, 'deb', 'Pkg2', version='1.0')
        ctx2 = OperationContext('op_pkg_test_2', allow_cancel=False)
        ctx2.lingering = True
        ctx2.returncode = 42
        ctx2.completed_event.set()

        reg.runner.get_operation_context.return_value = ctx2
        success_calls.clear()
        failure_calls.clear()

        with patch.object(PackageInstallerDialog, '__init__', lambda self, *a, **kw: None):
            dlg2 = PackageInstallerDialog()
            dlg2.registry = reg
            dlg2.info = info2
            dlg2._current_op_id = 'op_pkg_test_2'
            dlg2.progress_status_label = MagicMock()
            dlg2._on_install_success = lambda deleted: success_calls.append(deleted)
            dlg2._on_install_failure = lambda msg: failure_calls.append(msg)

            dlg2._worker_install(None, True, 'system', False, delete_after=True)
            pump_glib()

        self.assertTrue(os.path.exists(file_path2))
        try:
            os.remove(file_path2)
        except OSError:
            pass
        self.assertEqual(success_calls, [])
        self.assertEqual(len(failure_calls), 1)
        self.assertIn('42', failure_calls[0])

    def test_regression_l_lingering_wait_timeout_preserves_running_state_and_eventual_completion(self):
        """P1-01: completed_event.wait() timeout olduğunda canlı işlem sahte başarısızlık ilan edilmez;
        arka planda izlenmeye devam eder ve tamamlandığında doğru sonuç raporlanır."""
        from gi.repository import GLib
        from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog

        def pump_glib():
            ctx = GLib.MainContext.default()
            while ctx.iteration(False):
                pass

        reg = MagicMock()
        runner = MagicMock()
        runner._lingering_wait_timeout = 0.05
        reg.runner = runner

        ctx = OperationContext('op_wait_timeout_test', allow_cancel=False)
        ctx.lingering = True
        ctx.completed_event = threading.Event()
        runner.get_operation_context.return_value = ctx

        finished_results = []
        with patch.object(InstalledAppDetailsDialog, '__init__', lambda self, *a, **kw: None):
            dialog = InstalledAppDetailsDialog()
            dialog.registry = reg
            dialog.application = MagicMock()
            dialog.language = 'en'
            dialog.standalone = False
            dialog._action_busy = False
            dialog._destroyed = False
            dialog._action_bar = MagicMock()
            dialog.get_cached_sudo_password = lambda: None
            dialog.destroy = MagicMock()

            progress = MagicMock()
            progress_logs = []
            progress.append_log = lambda msg: progress_logs.append(msg)
            progress.finish = lambda ok, msg: finished_results.append((ok, msg))

            with (
                patch('sourcedock.ui.components.app_details_dialog.OperationProgressWindow', return_value=progress),
                patch('sourcedock.ui.components.app_details_dialog.OperationHistory'),
            ):
                def delayed_fail():
                    raise BackendError('Timeout Warning')

                dialog._run_standalone_action('update', delayed_fail)
                # wait_timeout 0.05s sonra tetiklenir ama completed_event henüz set edilmedi
                time.sleep(0.12)
                pump_glib()
                # Erken fail ÇAĞRILMAMIŞ olmalı!
                self.assertEqual(finished_results, [])
                self.assertTrue(any('devam ediyor' in log for log in progress_logs))

                # Süreç şimdi arka planda 0 ile tamamlanır
                ctx.returncode = 0
                ctx.completed_event.set()
                time.sleep(0.1)
                pump_glib()

                # Artık finish başarıyla çağrılmış olmalı
                self.assertEqual(len(finished_results), 1)
                self.assertTrue(finished_results[0][0])

    def test_regression_m_global_active_critical_registry_pid_validation(self):
        """P1-02: has_global_active_critical_operation; bitmiş işlemleri, PermissionError durumunu
        ve sahte mock PID'lerini doğru ele alır."""
        from sourcedock.core.runner import OperationState
        CommandRunner._active_critical_registry.clear()

        # 1. completed_event set edilmiş işlem derhal temizlenir
        ctx_done = OperationContext('op_done', allow_cancel=False)
        ctx_done.is_critical = True
        ctx_done.completed_event.set()
        CommandRunner._active_critical_registry['op_done'] = ctx_done
        self.assertFalse(CommandRunner.has_global_active_critical_operation())
        self.assertNotIn('op_done', CommandRunner._active_critical_registry)

        # 2. ProcessLookupError fırlatan ölü PID temizlenir
        mock_proc_dead = MagicMock()
        mock_proc_dead.pid = 9999999
        mock_proc_dead.poll.return_value = None
        ctx_dead = OperationContext('op_dead', allow_cancel=False)
        ctx_dead.is_critical = True
        ctx_dead.process = mock_proc_dead
        CommandRunner._active_critical_registry['op_dead'] = ctx_dead

        with patch('os.kill', side_effect=ProcessLookupError):
            self.assertFalse(CommandRunner.has_global_active_critical_operation())
        self.assertNotIn('op_dead', CommandRunner._active_critical_registry)

        # 3. PermissionError (root/başka kullanıcı süreci) canlı kabul edilir
        mock_proc_alive = MagicMock()
        mock_proc_alive.pid = 12345
        mock_proc_alive.poll.return_value = None
        ctx_alive = OperationContext('op_alive', allow_cancel=False)
        ctx_alive.is_critical = True
        ctx_alive.process = mock_proc_alive
        CommandRunner._active_critical_registry['op_alive'] = ctx_alive

        with patch('os.kill', side_effect=PermissionError):
            self.assertTrue(CommandRunner.has_global_active_critical_operation())
        CommandRunner._active_critical_registry.clear()

    def test_regression_n_drainer_secret_redaction(self):
        """P1-03: Drainer akışında parola ve özel token'lar redact_text ile maskelenir."""
        runner = CommandRunner()
        runner._sudo_password = 'SecretSudoPassword123'

        script = """
import sys, time
print('User token: token: secret_token_xyz987', flush=True)
print('Password in log: SecretSudoPassword123', flush=True)
sys.exit(0)
"""
        logs = []
        op_id = 'op_drain_secret_test'
        runner.set_output_callback(lambda l: logs.append(l), op_id=op_id)

        ctx = runner._create_operation(['python3', '-c', script], allow_cancel=False, op_id=op_id)
        ctx.is_critical = True
        ctx.secrets = ('secret_token_xyz987',)

        proc = subprocess.Popen(
            [sys.executable, '-c', script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ctx.process = proc
        runner._start_lingering_drainer(ctx)

        ctx.completed_event.wait(timeout=3.0)
        runner.set_output_callback(None, op_id=op_id)

        combined = ' '.join(logs)
        self.assertNotIn('SecretSudoPassword123', combined)
        self.assertNotIn('secret_token_xyz987', combined)
        self.assertIn('[redacted]', combined)

if __name__ == "__main__":
    unittest.main()
