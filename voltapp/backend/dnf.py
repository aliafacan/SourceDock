#!/usr/bin/env python3
"""DNF / RPM (Fedora/RHEL/CentOS) paket yöneticisi sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re

from voltapp.core.models import (
    SOURCE_DNF,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.base_native import BaseNativeProvider
from voltapp.backend.scanner import (
    DesktopEntryScanner,
    _clean_exec_command,
    _entry_has_non_apt_source,
    _first_category,
)


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class DnfProvider(BaseNativeProvider):
    """Fedora, RHEL ve CentOS sistemlerindeki DNF/RPM paketlerini yöneten sağlayıcı."""

    source = SOURCE_DNF
    display_name = "DNF"

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        super().__init__(runner, scanner)

    def is_available(self) -> bool:
        return self.runner.command_exists("dnf") or self.runner.command_exists("rpm")

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.runner.command_exists("rpm") or not self.scanner:
            return []

        desktop_entries = [
            entry
            for entry in self.scanner.list_entries(
                ["/usr/share/applications", os.path.expanduser("~/.local/share/applications")]
            )
            if entry.visible and not _entry_has_non_apt_source(entry)
        ]
        if not desktop_entries:
            return []

        owners = self._owning_packages([entry.path for entry in desktop_entries])
        if not owners:
            return []

        unique_packages = sorted(set(owners.values()))
        package_meta = self._package_metadata(unique_packages)
        upgradable = self._upgradable_packages()

        applications: list[UnifiedApplication] = []
        for entry in desktop_entries:
            package = owners.get(entry.path)
            if not package:
                continue
            meta = package_meta.get(package, {})
            version = meta.get("version", "")
            size_bytes = meta.get("size", 0)
            install_date = meta.get("install_date", "")
            size_kib = (size_bytes // 1024) if size_bytes else None

            applications.append(
                UnifiedApplication(
                    id=f"{SOURCE_DNF}:{package}:{Path(entry.path).name}",
                    name=entry.name,
                    source=SOURCE_DNF,
                    version=version,
                    icon=entry.icon or "application-x-executable",
                    executable=_clean_exec_command(entry.exec_command),
                    desktop_file=entry.path,
                    install_path=str(Path(entry.path).parent),
                    category=_first_category(entry.categories),
                    package_name=package,
                    update_available=package in upgradable,
                    installed_size_kib=size_kib,
                    installed_date=install_date,
                    last_updated=install_date,
                )
            )

        self._hidden_upgradable = upgradable - set(owners.values())
        return applications

    def _owning_packages(self, paths: list[str]) -> dict[str, str]:
        if not paths:
            return {}
        # rpm -qf paths
        result = self.runner.run(["rpm", "-qf", *paths, "--qf", "%{FILENAMES}\t%{NAME}\n"], timeout=30)
        owners: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            p, pkg = line.split("\t", 1)
            p = p.strip()
            pkg = pkg.strip()
            if p and pkg and not pkg.startswith("file "):
                owners[p] = pkg
        return owners

    def _package_metadata(self, packages: list[str]) -> dict[str, dict]:
        if not packages:
            return {}
        result = self.runner.run(
            ["rpm", "-q", *packages, "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{SIZE}\t%{INSTALLTIME}\n"],
            timeout=30,
        )
        metadata: dict[str, dict] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            pkg = parts[0].strip()
            ver = parts[1].strip()
            size = _safe_int(parts[2].strip()) or 0
            ts = _safe_int(parts[3].strip())
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
            metadata[pkg] = {
                "version": ver,
                "size": size,
                "install_date": date_str,
            }
        return metadata

    def _upgradable_packages(self) -> set[str]:
        if not self.runner.command_exists("dnf"):
            return set()
        # dnf check-update returns code 100 when updates exist, 0 when none
        result = self.runner.run(["dnf", "check-update", "-q"], timeout=45)
        packages: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("Last metadata") or line.startswith("Security:"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pkg_name = parts[0].split(".")[0]
                if pkg_name:
                    packages.add(pkg_name)
        return packages

    def list_all_packages(self) -> list[PackageInfo]:
        if not self.runner.command_exists("rpm"):
            return []
        result = self.runner.run(
            ["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{SIZE}\t%{SUMMARY}\n"],
            timeout=60,
        )
        upgradable = self._upgradable_packages()
        packages: list[PackageInfo] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name = parts[0].strip()
            version = parts[1].strip()
            size_bytes = _safe_int(parts[2].strip()) or 0
            summary = parts[3].strip()
            size_kib = (size_bytes // 1024) if size_bytes else None

            packages.append(
                PackageInfo(
                    name=name,
                    version=version,
                    installed_size_kib=size_kib,
                    description=summary,
                    update_available=name in upgradable,
                    new_version="",
                )
            )
        return sorted(packages, key=lambda p: p.name)

    def search_store(self, query: str) -> list[StoreResult]:
        if not self.runner.command_exists("dnf"):
            return []
        try:
            res = self.runner.run(["dnf", "search", "-q", query], timeout=30)
            items: list[StoreResult] = []
            current_name = ""
            current_desc = ""
            for line in res.stdout.splitlines():
                if " : " in line:
                    if current_name:
                        items.append(
                            StoreResult(
                                name=current_name,
                                app_id=current_name,
                                description=current_desc,
                                source=SOURCE_DNF,
                                version="",
                                remote="fedora",
                            )
                        )
                    name_part, desc_part = line.split(" : ", 1)
                    current_name = name_part.strip().split(".")[0]
                    current_desc = desc_part.strip()
                elif current_name:
                    current_desc += " " + line.strip()

            if current_name:
                items.append(
                    StoreResult(
                        name=current_name,
                        app_id=current_name,
                        description=current_desc,
                        source=SOURCE_DNF,
                        version="",
                        remote="fedora",
                    )
                )
            return items[:60]
        except Exception:
            return []

    def install_command(self, package: str) -> list[str]:
        return ["dnf", "install", "-y", package]

    def update_command(self, package: str) -> list[str]:
        return ["dnf", "upgrade", "-y", package]

    def update_all_command(self) -> list[str]:
        return ["dnf", "upgrade", "-y"]

    def remove_command(self, package: str, purge: bool = False) -> list[str]:
        return ["dnf", "remove", "-y", package]

    def refresh_cache_command(self) -> list[str]:
        return ["dnf", "makecache"]

    def get_lock_holders(self) -> list[tuple[str, str]]:
        holders: list[tuple[str, str]] = []
        try:
            res = self.runner.run(["pgrep", "-a", "-f", r"\b(dnf|rpm)\b"], timeout=5)
            cur_pid = str(os.getpid())
            for line in res.stdout.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2 and parts[0] != cur_pid:
                    holders.append((parts[0], parts[1][:140]))
        except Exception:
            pass
        return holders
