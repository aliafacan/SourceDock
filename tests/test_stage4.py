#!/usr/bin/env python3
"""Aşama 4 (Yeni Paket Formatları) birim ve entegrasyon testleri."""

import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
import zipfile

from voltapp.core.models import SOURCE_PORTABLE, LocalPackageInfo
from voltapp.core.runner import CommandRunner
from voltapp.backend.local_packages import (
    detect_package_format,
    inspect_local_package,
    inspect_deb,
    inspect_archive,
    inspect_flatpakref,
    install_local_archive,
)
from voltapp.backend.portable import (
    PortableProvider,
    load_portable_registry,
    register_portable_app,
    unregister_portable_app,
)
from voltapp.backend.manager import ApplicationRegistry


class TestStage4FormatDetection(unittest.TestCase):
    def test_detect_package_format(self):
        self.assertEqual(detect_package_format("test.deb"), "deb")
        self.assertEqual(detect_package_format("app.AppImage"), "appimage")
        self.assertEqual(detect_package_format("archive.tar.gz"), "archive")
        self.assertEqual(detect_package_format("archive.tar.xz"), "archive")
        self.assertEqual(detect_package_format("archive.zip"), "archive")
        self.assertEqual(detect_package_format("repo.flatpakref"), "flatpakref")
        self.assertEqual(detect_package_format("bundle.flatpak"), "flatpak")
        self.assertEqual(detect_package_format("fedora.rpm"), "rpm")
        self.assertIsNone(detect_package_format("unknown.txt"))


class TestDebInspection(unittest.TestCase):
    def test_inspect_real_deb(self):
        deb_path = "packaging/zorin-app-manager_0.2.0_all.deb"
        if not os.path.exists(deb_path):
            self.skipTest("Deb dosyası bulunamadı.")
        runner = CommandRunner()
        info = inspect_local_package(runner, deb_path)
        self.assertEqual(info.format, "deb")
        self.assertEqual(info.name, "zorin-app-manager")
        self.assertEqual(info.version, "0.2.0")
        self.assertEqual(info.architecture, "all")
        self.assertGreater(info.size_bytes, 0)
        self.assertTrue(len(info.description) > 0)


class TestFlatpakrefInspection(unittest.TestCase):
    def test_inspect_flatpakref(self):
        with tempfile.NamedTemporaryFile("w", suffix=".flatpakref", delete=False) as tf:
            tf.write(
                "[Flatpak Ref]\n"
                "Name=org.test.SampleApp\n"
                "Title=Sample Application\n"
                "Branch=stable\n"
                "Comment=A sample test application\n"
                "Description=Detailed long description of sample app\n"
                "Url=https://flathub.org/repo/\n"
            )
            temp_path = tf.name

        try:
            info = inspect_flatpakref(temp_path)
            self.assertEqual(info.format, "flatpakref")
            self.assertEqual(info.name, "Sample Application")
            self.assertEqual(info.version, "stable")
            self.assertEqual(info.summary, "A sample test application")
            self.assertEqual(info.extra_info.get("remote_url"), "https://flathub.org/repo/")
        finally:
            os.remove(temp_path)


class TestArchiveInstallationAndPortableProvider(unittest.TestCase):
    def test_archive_lifecycle(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmp_root:
            orig_xdg = os.environ.get("XDG_DATA_HOME")
            os.environ["XDG_DATA_HOME"] = tmp_root
            try:
                archive_path = os.path.join(tmp_root, "super-editor-1.5.0-linux.tar.gz")
                with tarfile.open(archive_path, "w:gz") as tar:
                    # 1. Executable script
                    bin_data = b"#!/bin/bash\necho 'hello from editor'\n"
                    ti = tarfile.TarInfo(name="super-editor/bin/super-editor")
                    ti.size = len(bin_data)
                    ti.mode = 0o755
                    import io
                    tar.addfile(ti, io.BytesIO(bin_data))

                    # 2. Desktop file
                    desktop_data = b"[Desktop Entry]\nName=Super Editor\nType=Application\n"
                    ti2 = tarfile.TarInfo(name="super-editor/super-editor.desktop")
                    ti2.size = len(desktop_data)
                    tar.addfile(ti2, io.BytesIO(desktop_data))

                # İnceleme testi
                info = inspect_local_package(runner, archive_path)
                self.assertEqual(info.format, "archive")
                self.assertIn("Super Editor", info.name)

                # Kurulum testi
                extract_target_base = os.path.join(tmp_root, "installed_apps")
                app_dir, exec_path = install_local_archive(
                    runner,
                    archive_path,
                    extract_dir=extract_target_base,
                    create_desktop=True,
                )
                self.assertTrue(os.path.isdir(app_dir))
                self.assertTrue(os.path.isfile(exec_path))
                self.assertTrue(os.access(exec_path, os.X_OK))

                # Provider listeleme testi
                provider = PortableProvider(runner)
                apps = provider.list_applications()
                installed = [a for a in apps if "super_editor" in a.id or "super editor" in a.name.lower()]
                self.assertTrue(len(installed) >= 1)
                app = installed[0]
                self.assertEqual(app.source, SOURCE_PORTABLE)

                # Kaldırma testi
                provider.remove(app)
                self.assertFalse(os.path.exists(app_dir))
            finally:
                if orig_xdg is not None:
                    os.environ["XDG_DATA_HOME"] = orig_xdg
                else:
                    os.environ.pop("XDG_DATA_HOME", None)


class TestApplicationRegistryIntegration(unittest.TestCase):
    def test_registry_has_portable_provider(self):
        registry = ApplicationRegistry()
        sources = [p.source for p in registry.providers]
        self.assertIn(SOURCE_PORTABLE, sources)


class TestPackageInstallerDialog(unittest.TestCase):
    def test_dialog_creation(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            self.skipTest("GUI display (X11/Wayland) mevcut değil.")

        from voltapp.ui.components.package_installer_dialog import PackageInstallerDialog

        info = LocalPackageInfo(
            file_path="/tmp/fake.deb",
            format="deb",
            name="Sample App",
            version="1.0.0",
            summary="A short summary",
            description="A detailed long description",
            size_bytes=1048576,
            architecture="amd64",
            maintainer="Test Dev <dev@test.org>",
            dependencies=["libc6", "python3"],
        )
        parent = Gtk.Window()
        dialog = PackageInstallerDialog(parent, info, language="tr")
        self.assertEqual(dialog.info.name, "Sample App")
        self.assertTrue(dialog.should_create_desktop)
        dialog.destroy()
        parent.destroy()


class TestFlatpakInstallScope(unittest.TestCase):
    def test_flatpak_scope_command_formation(self):
        from unittest.mock import MagicMock
        from voltapp.backend.local_packages import install_local_flatpak

        mock_runner = MagicMock()
        mock_runner.command_exists.return_value = True

        # 1. Varsayılan --user scope testi
        install_local_flatpak(mock_runner, "/path/to/app.flatpak", scope="--user")
        mock_runner.run.assert_called_once()
        called_cmd = mock_runner.run.call_args[0][0]
        self.assertIn("--user", called_cmd)
        self.assertIn("/path/to/app.flatpak", called_cmd)
        self.assertNotIn("--system", called_cmd)

        mock_runner.reset_mock()

        # 2. --system scope testi
        install_local_flatpak(mock_runner, "/path/to/app.flatpak", scope="--system")
        mock_runner.run_privileged.assert_called_once()
        called_sys_cmd = mock_runner.run_privileged.call_args[0][0]
        self.assertIn("--system", called_sys_cmd)
        self.assertIn("/path/to/app.flatpak", called_sys_cmd)

        mock_runner.reset_mock()

        # 3. reinstall=True testi
        install_local_flatpak(mock_runner, "/path/to/app.flatpak", scope="--system", reinstall=True)
        called_reinst_cmd = mock_runner.run_privileged.call_args[0][0]
        self.assertIn("--reinstall", called_reinst_cmd)

    def test_flatpak_already_installed_graceful_recovery(self):
        from unittest.mock import MagicMock
        from voltapp.backend.local_packages import install_local_flatpak
        from voltapp.core.runner import BackendError

        mock_runner = MagicMock()
        mock_runner.command_exists.return_value = True
        mock_runner.run_privileged.side_effect = BackendError("hata: ai.example.App'in bu sürümü zaten kurulu. already installed.")

        # Hata fırlatılmamalı, nazikçe karşılanıp başarı kabul edilmeli
        try:
            install_local_flatpak(mock_runner, "/path/to/app.flatpak", scope="--system")
        except BackendError:
            self.fail("install_local_flatpak 'already installed' hatasında istisna fırlatmamalı!")


class TestAppImageMove(unittest.TestCase):
    def test_appimage_is_moved(self):
        from voltapp.backend.local_packages import install_local_appimage
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmp_downloads, tempfile.TemporaryDirectory() as tmp_apps:
            src = Path(tmp_downloads) / "TestApp-x86_64.AppImage"
            src.write_text("#!/bin/sh\necho test\n")

            dest = install_local_appimage(runner, str(src), target_dir=tmp_apps, create_desktop=False)
            self.assertTrue(os.path.exists(dest))
            self.assertFalse(src.exists(), "AppImage taşınmış olmalı ve kaynak indirme dosyasında kalmamalı!")


if __name__ == "__main__":
    unittest.main()

