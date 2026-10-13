#!/usr/bin/env python3
"""Aşama 5: Dağıtımdan Bağımsız Mimari (Distro-Agnostic) Birim Testleri."""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from voltapp.core.models import (
    NATIVE_SOURCES,
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_FLATPAK,
    SOURCE_PACMAN,
    SOURCE_SNAP,
    SOURCE_ZYPPER,
    StoreResult,
    UnifiedApplication,
    is_native_source,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.distro import DistroInfo, detect_distro, parse_os_release
from voltapp.backend.base_native import BaseNativeProvider
from voltapp.backend.apt import AptProvider
from voltapp.backend.dnf import DnfProvider
from voltapp.backend.pacman import PacmanProvider
from voltapp.backend.zypper import ZypperProvider
from voltapp.backend.manager import ApplicationRegistry
from voltapp.store.registry import StoreRegistry


class TestDistroDetection(unittest.TestCase):
    """Farklı Linux dağıtımlarının ve yerel paket yöneticilerinin tespiti."""

    def test_parse_os_release(self):
        content = """NAME="Fedora Linux"
VERSION="40 (Workstation Edition)"
ID=fedora
VERSION_ID=40
ID_LIKE="rhel centos"
PRETTY_NAME="Fedora Linux 40 (Workstation Edition)"
"""
        parsed = parse_os_release(content)
        self.assertEqual(parsed["ID"], "fedora")
        self.assertEqual(parsed["VERSION_ID"], "40")
        self.assertEqual(parsed["ID_LIKE"], "rhel centos")

    def test_detect_fedora(self):
        content = 'NAME="Fedora Linux"\nID=fedora\nID_LIKE="rhel centos"\nVERSION_ID="40"\n'
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.read_text", return_value=content):
            mock_runner = MagicMock()
            mock_runner.command_exists.side_effect = lambda cmd: cmd in ("dnf", "rpm")
            info = detect_distro(runner=mock_runner)
            self.assertEqual(info.id, "fedora")
            self.assertTrue(info.is_fedora_family)
            self.assertEqual(info.native_manager, SOURCE_DNF)

    def test_detect_arch(self):
        content = 'NAME="Arch Linux"\nID=arch\nPRETTY_NAME="Arch Linux"\n'
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.read_text", return_value=content):
            mock_runner = MagicMock()
            mock_runner.command_exists.side_effect = lambda cmd: cmd == "pacman"
            info = detect_distro(runner=mock_runner)
            self.assertEqual(info.id, "arch")
            self.assertTrue(info.is_arch_family)
            self.assertEqual(info.native_manager, SOURCE_PACMAN)

    def test_detect_opensuse(self):
        content = 'NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.read_text", return_value=content):
            mock_runner = MagicMock()
            mock_runner.command_exists.side_effect = lambda cmd: cmd in ("zypper", "rpm")
            info = detect_distro(runner=mock_runner)
            self.assertTrue(info.is_suse_family)
            self.assertEqual(info.native_manager, SOURCE_ZYPPER)

    def test_detect_zorin_ubuntu(self):
        content = 'NAME="Zorin OS"\nID=zorin\nID_LIKE="ubuntu debian"\nVERSION_ID="18"\n'
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.read_text", return_value=content):
            mock_runner = MagicMock()
            mock_runner.command_exists.side_effect = lambda cmd: cmd in ("apt", "dpkg-query", "apt-get")
            info = detect_distro(runner=mock_runner)
            self.assertTrue(info.is_debian_family)
            self.assertEqual(info.native_manager, SOURCE_APT)


class TestNativeProviders(unittest.TestCase):
    """DNF, Pacman, Zypper sağlayıcılarının komut ve çıktı çözümlemeleri."""

    def test_is_native_source_helper(self):
        self.assertTrue(is_native_source(SOURCE_APT))
        self.assertTrue(is_native_source(SOURCE_DNF))
        self.assertTrue(is_native_source(SOURCE_PACMAN))
        self.assertTrue(is_native_source(SOURCE_ZYPPER))
        self.assertFalse(is_native_source(SOURCE_FLATPAK))
        self.assertFalse(is_native_source(SOURCE_SNAP))

    def test_dnf_commands(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        provider = DnfProvider(runner, MagicMock())

        self.assertEqual(provider.install_command("vlc"), ["dnf", "install", "-y", "vlc"])
        self.assertEqual(provider.update_command("vlc"), ["dnf", "upgrade", "-y", "vlc"])
        self.assertEqual(provider.update_all_command(), ["dnf", "upgrade", "-y"])
        self.assertEqual(provider.remove_command("vlc"), ["dnf", "remove", "-y", "vlc"])
        self.assertEqual(provider.refresh_cache_command(), ["dnf", "makecache"])

    def test_dnf_parsing(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        # Mock calls: first rpm -qa, then dnf check-update
        runner.run.side_effect = [
            # rpm -qa
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="firefox\t124.0-1.fc40\t150000000\tMozilla Firefox Browser\ncurl\t8.6.0-1.fc40\t500000\tCommand line tool for transferring data\n",
            ),
            # dnf check-update
            subprocess.CompletedProcess(args=[], returncode=100, stdout="firefox.x86_64 125.0-1.fc40 updates\n"),
        ]
        provider = DnfProvider(runner, MagicMock())
        pkgs = provider.list_all_packages()
        self.assertEqual(len(pkgs), 2)
        firefox = next(p for p in pkgs if p.name == "firefox")
        self.assertEqual(firefox.version, "124.0-1.fc40")
        self.assertTrue(firefox.update_available)

    def test_pacman_commands(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        provider = PacmanProvider(runner, MagicMock())

        self.assertEqual(provider.install_command("neovim"), ["pacman", "-S", "--noconfirm", "neovim"])
        self.assertEqual(provider.update_command("neovim"), ["pacman", "-S", "--noconfirm", "neovim"])
        self.assertEqual(provider.update_all_command(), ["pacman", "-Syu", "--noconfirm"])
        self.assertEqual(provider.remove_command("neovim"), ["pacman", "-R", "--noconfirm", "neovim"])
        self.assertEqual(provider.remove_command("neovim", purge=True), ["pacman", "-Rns", "--noconfirm", "neovim"])
        self.assertEqual(provider.refresh_cache_command(), ["pacman", "-Sy"])

    def test_pacman_parsing(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = [
            # pacman -Q
            subprocess.CompletedProcess(args=[], returncode=0, stdout="gimp 2.10.38-1\ninkscape 1.3.2-1\n"),
            # pacman -Qu
            subprocess.CompletedProcess(args=[], returncode=0, stdout="gimp 2.10.38-1 -> 2.10.38-2\n"),
        ]
        provider = PacmanProvider(runner, MagicMock())
        pkgs = provider.list_all_packages()
        self.assertEqual(len(pkgs), 2)
        gimp = next(p for p in pkgs if p.name == "gimp")
        self.assertTrue(gimp.update_available)
        self.assertEqual(gimp.new_version, "2.10.38-2")

    def test_zypper_commands(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        provider = ZypperProvider(runner, MagicMock())

        self.assertEqual(provider.install_command("htop"), ["zypper", "--non-interactive", "install", "-y", "htop"])
        self.assertEqual(provider.update_command("htop"), ["zypper", "--non-interactive", "update", "-y", "htop"])
        self.assertEqual(provider.update_all_command(), ["zypper", "--non-interactive", "update", "-y"])
        self.assertEqual(provider.remove_command("htop"), ["zypper", "--non-interactive", "remove", "-y", "-u", "htop"])
        self.assertEqual(provider.refresh_cache_command(), ["zypper", "--non-interactive", "refresh"])


class TestRegistryMultiDistroDispatch(unittest.TestCase):
    """ApplicationRegistry ve StoreRegistry'nin dağıtım bağımsız çağrı yönlendirmesi."""

    def test_registry_selects_detected_provider(self):
        mock_runner = MagicMock()
        mock_runner.command_exists.side_effect = lambda cmd: cmd in ("dnf", "rpm")

        distro = DistroInfo(id="fedora", name="Fedora", native_manager=SOURCE_DNF)
        registry = ApplicationRegistry(distro_info=distro, runner=mock_runner)

        self.assertEqual(registry.native_provider.source, SOURCE_DNF)
        self.assertIsInstance(registry.native_provider, DnfProvider)

    def test_registry_update_native_dispatch(self):
        mock_runner = MagicMock()
        mock_runner.command_exists.return_value = True
        distro = DistroInfo(id="arch", name="Arch", native_manager=SOURCE_PACMAN)
        registry = ApplicationRegistry(distro_info=distro, runner=mock_runner)

        app = UnifiedApplication(
            id="pacman:code:code.desktop",
            name="Visual Studio Code",
            source=SOURCE_PACMAN,
            package_name="code",
        )
        registry.update(app)
        mock_runner.run_privileged.assert_called_with(["pacman", "-S", "--noconfirm", "code"], timeout=1800)

    def test_registry_remove_native_dispatch(self):
        mock_runner = MagicMock()
        mock_runner.command_exists.return_value = True
        distro = DistroInfo(id="fedora", name="Fedora", native_manager=SOURCE_DNF)
        registry = ApplicationRegistry(distro_info=distro, runner=mock_runner)

        app = UnifiedApplication(
            id="dnf:vlc:vlc.desktop",
            name="VLC media player",
            source=SOURCE_DNF,
            package_name="vlc",
        )
        registry.remove(app)
        mock_runner.run_privileged.assert_called_with(["dnf", "remove", "-y", "vlc"], timeout=1800)

    def test_store_registry_native_install(self):
        distro = DistroInfo(id="fedora", name="Fedora", native_manager=SOURCE_DNF)
        store = StoreRegistry(distro_info=distro)
        store._run_privileged_streaming = MagicMock()

        res = StoreResult(
            name="Blender",
            app_id="blender",
            description="3D creation suite",
            source=SOURCE_DNF,
            version="4.1.0",
            remote="fedora",
        )
        store.install(res)
        store._run_privileged_streaming.assert_called_with(["dnf", "install", "-y", "blender"], timeout=1800)


if __name__ == "__main__":
    unittest.main()
