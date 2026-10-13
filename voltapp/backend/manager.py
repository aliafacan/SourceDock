#!/usr/bin/env python3
"""Tüm yüklü uygulama kaynaklarını birleştiren ve yöneten koordinatör (Registry)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from voltapp.core.errors import BackendError
from voltapp.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    PACKAGE_MANAGER_SOURCES,
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_PORTABLE,
    SOURCE_SNAP,
    ApplicationIssue,
    ApplicationSnapshot,
    LocalPackageInfo,
    PackageInfo,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import (
    DesktopEntryScanner,
    _clean_exec_parts,
    _name_from_appimage,
    _normalize_name,
    _normalize_path,
)
from voltapp.backend.apt import AptProvider
from voltapp.backend.flatpak import FlatpakProvider
from voltapp.backend.snap import SnapProvider
from voltapp.backend.appimage import AppImageProvider
from voltapp.backend.portable import PortableProvider


def _apt_command(*args: str) -> list[str]:
    return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, *args]


class ApplicationRegistry:
    """Sistemdeki tüm kurulu paket kaynaklarını yöneten ana kayıt defteri."""

    def __init__(self):
        self.runner = CommandRunner()
        self.scanner = DesktopEntryScanner(self.runner)
        self.applications: list[UnifiedApplication] = []
        self.providers = [
            AptProvider(self.runner, self.scanner),
            FlatpakProvider(self.runner, self.scanner),
            SnapProvider(self.runner, self.scanner),
            AppImageProvider(self.runner, self.scanner),
            PortableProvider(self.runner),
        ]

    def set_sudo_password(self, password: str) -> None:
        self.runner.set_sudo_password(password)

    def refresh_update_cache(self) -> None:
        if self.runner.command_exists("apt-get"):
            self.runner.run_privileged(_apt_command("update", "-q"), timeout=120)
        if self.runner.command_exists("flatpak"):
            self.runner.run(["flatpak", "update", "--appstream", "-y"], timeout=60, check=False)
        if self.runner.command_exists("snap"):
            self.runner.run_privileged(["snap", "refresh", "--list"], timeout=30)

    def refresh_update_cache_silent(self) -> None:
        try:
            sudo_free = self.runner.run(["sudo", "-n", "true"], timeout=5).returncode == 0
            if sudo_free and self.runner.command_exists("apt-get"):
                self.runner.run(["sudo", "-n", *_apt_command("update", "-q")], timeout=90, check=False)
        except Exception:
            pass
        try:
            if self.runner.command_exists("flatpak"):
                self.runner.run(["flatpak", "update", "--appstream", "-y"], timeout=60, check=False)
        except Exception:
            pass

    def load(self) -> ApplicationSnapshot:
        applications: list[UnifiedApplication] = []
        provider_errors: list[str] = []
        for provider in self.providers:
            try:
                applications.extend(provider.list_applications())
            except BackendError as exc:
                provider_errors.append(f"{provider.source}: {exc}")
            except Exception as exc:
                provider_errors.append(f"{provider.source}: {exc}")

        apt_provider = next((p for p in self.providers if isinstance(p, AptProvider)), None)
        if apt_provider is not None:
            hidden = getattr(apt_provider, "_hidden_upgradable", set())
            if hidden:
                names = ", ".join(sorted(hidden))
                provider_errors.append(f"apt (sistem): {len(hidden)} arayüzsüz paket güncellenebilir → {names}")

        merged = self._merge_applications(applications)
        self.applications = merged
        issues = self.diagnose(merged)
        return ApplicationSnapshot(applications=merged, issues=issues, provider_errors=provider_errors)

    def list_packages(self) -> list[PackageInfo]:
        apt_provider = next((p for p in self.providers if isinstance(p, AptProvider)), None)
        if apt_provider is None:
            return []
        return apt_provider.list_all_packages()

    def update_packages(self, names: list[str]) -> None:
        if not names:
            return
        self.runner.run_privileged(_apt_command("install", "--only-upgrade", "-y", *names), timeout=1800)

    def launch(self, application: UnifiedApplication) -> None:
        if application.source == SOURCE_FLATPAK:
            self.runner.spawn(["flatpak", "run", application.package_name])
            return
        if application.source == SOURCE_SNAP:
            command = _clean_exec_parts(application.executable) or [f"/snap/bin/{application.package_name}"]
            self.runner.spawn(command)
            return
        if application.source == SOURCE_APPIMAGE:
            self.runner.spawn([application.install_path])
            return
        if application.source == SOURCE_PORTABLE:
            if application.executable and os.path.exists(application.executable):
                self.runner.spawn([application.executable])
                return

        command = _clean_exec_parts(application.executable)
        if not command:
            raise BackendError("Uygulama komutu bulunamadi.")
        self.runner.spawn(command)

    def open_location(self, application: UnifiedApplication) -> None:
        target = application.install_path or application.desktop_file
        if not target:
            raise BackendError("Konum bulunamadi.")
        if os.path.isfile(target):
            target = str(Path(target).parent)
        if self.runner.command_exists("xdg-open"):
            self.runner.spawn(["xdg-open", target])
            return
        self.runner.spawn(["gio", "open", target])

    def update(self, application: UnifiedApplication) -> None:
        if application.source == SOURCE_APT:
            package = application.package_name
            self.runner.run_privileged(_apt_command("install", "--only-upgrade", "-y", package), timeout=1800)
            return
        if application.source == SOURCE_FLATPAK:
            user_base = os.path.expanduser("~/.local/share/flatpak")
            scope = "--user" if application.install_path.startswith(user_base) else "--system"
            self.runner.run(["flatpak", "update", scope, "-y", application.package_name], timeout=1800, check=True)
            return
        if application.source == SOURCE_SNAP:
            self.runner.run_privileged(["snap", "refresh", application.package_name], timeout=1800)
            return
        if application.source == SOURCE_APPIMAGE:
            if not application.update_supported:
                raise BackendError("Manual update required")
            self.runner.run(["AppImageUpdate", application.install_path], timeout=1800, check=True)
            return
        raise BackendError("Bilinmeyen uygulama kaynagi.")

    def update_all(self, applications: list[UnifiedApplication]) -> None:
        sources = {application.source for application in applications}
        if SOURCE_APT in sources and self.runner.command_exists("apt-get"):
            if self.runner.command_exists("nala"):
                self.runner.run_privileged(["nala", "upgrade", "-y"], timeout=3600)
            else:
                self.runner.run_privileged(_apt_command("upgrade", "-y"), timeout=3600)
        if SOURCE_FLATPAK in sources and self.runner.command_exists("flatpak"):
            self.runner.run(["flatpak", "update", "-y"], timeout=3600, check=True)
        if SOURCE_SNAP in sources and self.runner.command_exists("snap"):
            self.runner.run_privileged(["snap", "refresh"], timeout=3600)
        for application in applications:
            if application.source == SOURCE_APPIMAGE and application.update_supported:
                self.runner.run(["AppImageUpdate", application.install_path], timeout=1800, check=False)

    def remove(self, application: UnifiedApplication, purge: bool = False) -> None:
        if application.source == SOURCE_APT:
            cmd = "purge" if purge else "remove"
            self.runner.run_privileged(_apt_command(cmd, "-y", application.package_name), timeout=1800)
            if purge:
                self.runner.run_privileged(_apt_command("autoremove", "-y"), timeout=600)
                self._remove_user_data_dirs(application.package_name)
            return
        if application.source == SOURCE_FLATPAK:
            user_base = os.path.expanduser("~/.local/share/flatpak")
            scope = "--user" if application.install_path.startswith(user_base) else "--system"
            self.runner.run(["flatpak", "uninstall", scope, "-y", application.package_name], timeout=1800, check=True)
            if purge:
                data_dir = os.path.expanduser(f"~/.var/app/{application.package_name}")
                if os.path.isdir(data_dir):
                    shutil.rmtree(data_dir, ignore_errors=True)
                self._remove_user_data_dirs(application.package_name.rsplit(".", 1)[-1].lower())
            return
        if application.source == SOURCE_SNAP:
            cmd = ["snap", "remove"]
            if purge:
                cmd.append("--purge")
            cmd.append(application.package_name)
            self.runner.run_privileged(cmd, timeout=1800)
            return
        if application.source == SOURCE_APPIMAGE:
            self._remove_appimage(application)
            if purge:
                self._remove_user_data_dirs(application.name)
            return
        if application.source == SOURCE_PORTABLE:
            portable_provider = next((p for p in self.providers if isinstance(p, PortableProvider)), None)
            if portable_provider:
                portable_provider.remove(application, purge=purge)
            if purge:
                self._remove_user_data_dirs(application.name)
            return
        raise BackendError("Bilinmeyen uygulama kaynagi.")

    def flatpak_cleanup(self) -> None:
        if self.runner.command_exists("flatpak"):
            self.runner.run(["flatpak", "uninstall", "--user", "--unused", "-y"], timeout=300, check=False)
            self.runner.run_privileged(["flatpak", "uninstall", "--system", "--unused", "-y"], timeout=300)

    def flatpak_history(self, app_id: str) -> list[dict]:
        result = self.runner.run(["flatpak", "remote-info", "--log", "flathub", app_id], timeout=30)
        entries: list[dict] = []
        current: dict = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Commit:"):
                if current:
                    entries.append(current)
                current = {"commit": line.split(":", 1)[1].strip(), "version": "", "date": ""}
            elif line.startswith("Version:") and current:
                current["version"] = line.split(":", 1)[1].strip()
            elif line.startswith("Date:") and current:
                current["date"] = line.split(":", 1)[1].strip()
        if current:
            entries.append(current)
        return entries

    def flatpak_rollback(self, app_id: str, commit: str) -> None:
        self.runner.run(["flatpak", "update", "--commit", commit, "-y", app_id], timeout=1800, check=True)

    def flatpak_permissions(self, app_id: str) -> dict[str, list[str]]:
        result = self.runner.run(["flatpak", "override", "--show", app_id], timeout=10)
        perms: dict[str, list[str]] = {}
        section = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                perms[section] = []
            elif line and section:
                perms[section].append(line)
        return perms

    def flatpak_reset_permissions(self, app_id: str) -> None:
        self.runner.run(["flatpak", "override", "--reset", app_id], timeout=15, check=True)

    def export_app_list(self) -> str:
        data = [
            {
                "name": app.name,
                "source": app.source,
                "version": app.version,
                "package": app.package_name,
            }
            for app in self.applications
        ]
        return json.dumps(data, ensure_ascii=False, indent=2)

    def apt_changelog(self, package_name: str) -> str:
        import gzip as _gzip
        for gz_path in (
            f"/usr/share/doc/{package_name}/changelog.Debian.gz",
            f"/usr/share/doc/{package_name}/changelog.gz",
        ):
            if os.path.exists(gz_path):
                try:
                    with _gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
                        return f.read()
                except Exception:
                    pass
        for txt_path in (
            f"/usr/share/doc/{package_name}/changelog.Debian",
            f"/usr/share/doc/{package_name}/changelog",
        ):
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()
                except Exception:
                    pass
        return ""

    def register_appimage(self, path: str) -> None:
        from voltapp.backend.local_packages import install_local_appimage
        install_local_appimage(self.runner, path)

    def inspect_local_package(self, path: str) -> LocalPackageInfo:
        from voltapp.backend.local_packages import inspect_local_package
        return inspect_local_package(self.runner, path)

    def is_local_package_installed(self, info: LocalPackageInfo) -> bool:
        from voltapp.backend.local_packages import is_package_installed
        return is_package_installed(self.runner, info)

    def install_local_package(
        self,
        info: LocalPackageInfo,
        target_dir: str | None = None,
        create_desktop: bool = True,
        scope: str = "--user",
        reinstall: bool = False,
    ) -> None:
        from voltapp.backend.local_packages import (
            install_local_deb,
            install_local_appimage,
            install_local_archive,
            install_local_flatpak,
            install_local_rpm,
        )
        if info.format == "deb":
            install_local_deb(self.runner, info.file_path)
        elif info.format == "appimage":
            install_local_appimage(self.runner, info.file_path, target_dir=target_dir, create_desktop=create_desktop)
        elif info.format == "archive":
            install_local_archive(self.runner, info.file_path, extract_dir=target_dir, create_desktop=create_desktop)
        elif info.format in ("flatpakref", "flatpak"):
            install_local_flatpak(self.runner, info.file_path, scope=scope, reinstall=reinstall)
        elif info.format == "rpm":
            install_local_rpm(self.runner, info.file_path)
        else:
            raise BackendError(f"Desteklenmeyen paket formati: {info.format}")

    def _remove_user_data_dirs(self, name: str) -> None:
        name_lower = re.sub(r"[\s_]", "-", name.strip().lower())
        for base_dir in (
            os.path.expanduser("~/.config"),
            os.path.expanduser("~/.local/share"),
            os.path.expanduser("~/.cache"),
        ):
            candidate = os.path.join(base_dir, name_lower)
            if os.path.isdir(candidate):
                shutil.rmtree(candidate, ignore_errors=True)

    def diagnose(self, applications: list[UnifiedApplication]) -> list[ApplicationIssue]:
        issues: list[ApplicationIssue] = []
        seen_names: dict[str, list[UnifiedApplication]] = {}
        for application in applications:
            key = _normalize_name(application.name)
            seen_names.setdefault(key, []).append(application)
            if not application.icon:
                issues.append(ApplicationIssue("missing_icon", application.name, "No icon is set.", application.desktop_file))
            if application.desktop_file and not application.executable:
                issues.append(ApplicationIssue("broken_desktop", application.name, "Desktop launcher has no command.", application.desktop_file))
            if application.source == SOURCE_APPIMAGE and application.install_path and not os.path.exists(application.install_path):
                issues.append(ApplicationIssue("broken_desktop", application.name, "Linked AppImage file is missing.", application.desktop_file))

        for duplicates in seen_names.values():
            source_set = {item.source for item in duplicates}
            if len(duplicates) > 1 and len(source_set) > 1:
                detail = ", ".join(sorted(item.source for item in duplicates))
                issues.append(ApplicationIssue("duplicate", duplicates[0].name, detail))
        return issues

    def _merge_applications(self, applications: list[UnifiedApplication]) -> list[UnifiedApplication]:
        by_id: dict[str, UnifiedApplication] = {}
        for application in applications:
            by_id[application.id] = application

        source_merged: dict[str, UnifiedApplication] = {}
        for application in by_id.values():
            key = self._dedupe_key(application)
            current = source_merged.get(key)
            if current is None or self._prefer(application, current):
                source_merged[key] = application

        grouped_by_name: dict[str, list[UnifiedApplication]] = {}
        for application in source_merged.values():
            grouped_by_name.setdefault(_normalize_name(application.name), []).append(application)

        merged: list[UnifiedApplication] = []
        for group in grouped_by_name.values():
            if len(group) > 1:
                merged.append(sorted(group, key=self._preference_sort_key)[0])
            else:
                merged.extend(group)
        return sorted(merged, key=lambda app: app.name.lower())

    def _dedupe_key(self, application: UnifiedApplication) -> str:
        if application.source in PACKAGE_MANAGER_SOURCES:
            return f"{application.source}:{application.package_name}:{Path(application.desktop_file).name}"
        if application.install_path:
            return f"{application.source}:{application.install_path}"
        return f"{application.source}:{_normalize_name(application.name)}"

    def _prefer(self, candidate: UnifiedApplication, current: UnifiedApplication) -> bool:
        if candidate.desktop_file and not current.desktop_file:
            return True
        if candidate.update_available and not current.update_available:
            return True
        cand_in_apps = bool(candidate.install_path and "/applications" in candidate.install_path.lower())
        curr_in_apps = bool(current.install_path and "/applications" in current.install_path.lower())
        if cand_in_apps and not curr_in_apps:
            return True
        return len(candidate.name) > len(current.name)

    def _preference_sort_key(self, application: UnifiedApplication) -> tuple[int, int, int, int, str]:
        source_priority = {
            SOURCE_APT: 0,
            SOURCE_FLATPAK: 1,
            SOURCE_SNAP: 2,
            SOURCE_APPIMAGE: 3,
            SOURCE_PORTABLE: 4,
        }.get(application.source, 9)
        in_apps = 0 if application.install_path and "/applications" in application.install_path.lower() else 1
        return (
            0 if application.update_available else 1,
            0 if application.desktop_file else 1,
            in_apps,
            source_priority,
            application.name.lower(),
        )

    def _remove_appimage(self, application: UnifiedApplication) -> None:
        if application.install_path and os.path.exists(application.install_path):
            os.remove(application.install_path)

        if not application.desktop_file or not os.path.exists(application.desktop_file):
            return

        try:
            entry = self.scanner.load_entry(application.desktop_file)
        except OSError:
            entry = None
        if entry and _normalize_path(entry.appimage_path) == _normalize_path(application.install_path):
            os.remove(application.desktop_file)

