#!/usr/bin/env python3
"""Pacman (Arch Linux / Manjaro / EndeavourOS) paket yöneticisi sağlayıcısı."""

from __future__ import annotations

import os
from pathlib import Path
import re

from sourcedock.core.models import (
    SOURCE_PACMAN,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.core.errors import BackendError
from sourcedock.backend.base_native import BaseNativeProvider
from sourcedock.backend.scanner import (
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


def _parse_size_str(val: str) -> int | None:
    """Örnek: '14.50 MiB', '520.00 KiB' değerlerini KiB cinsine çevirir."""
    val = val.strip().lower()
    match = re.match(r"([0-9.]+)\s*([kmg]?i?b)", val)
    if not match:
        return None
    num = float(match.group(1))
    unit = match.group(2)
    if "g" in unit:
        return int(num * 1024 * 1024)
    if "m" in unit:
        return int(num * 1024)
    if "k" in unit:
        return int(num)
    if "b" in unit:
        return int(num / 1024)
    return None


class PacmanProvider(BaseNativeProvider):
    """Arch Linux, Manjaro ve türevlerindeki Pacman paketlerini yöneten sağlayıcı."""

    source = SOURCE_PACMAN
    display_name = "Pacman"

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        super().__init__(runner, scanner)

    def is_available(self) -> bool:
        return self.runner.command_exists("pacman")

    def list_applications(self, *, include_updates: bool = True) -> list[UnifiedApplication]:
        if not self.runner.command_exists("pacman") or not self.scanner:
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
        upgradable = self._upgradable_packages() if include_updates else {}

        applications: list[UnifiedApplication] = []
        for entry in desktop_entries:
            package = owners.get(entry.path)
            if not package:
                continue
            meta = package_meta.get(package, {})
            version = meta.get("version", "")
            size_kib = meta.get("size_kib")
            install_date = meta.get("install_date", "")

            applications.append(
                UnifiedApplication(
                    id=f"{SOURCE_PACMAN}:{package}:{Path(entry.path).name}",
                    name=entry.name,
                    source=SOURCE_PACMAN,
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

        self._hidden_upgradable = set(upgradable.keys()) - set(owners.values())
        return applications

    def _owning_packages(self, paths: list[str]) -> dict[str, str]:
        if not paths:
            return {}
        owners: dict[str, str] = {}
        # Ensure LC_ALL=C is used so pacman outputs English "is owned by",
        # but also support localized formats (e.g. Turkish "paketine ait").
        env = {**os.environ, "LC_ALL": "C"}
        for path in paths:
            if not os.path.exists(path):
                continue
            result = self.runner.run(["env", "LC_ALL=C", "pacman", "-Qo", path], timeout=5)
            stdout = result.stdout.strip()
            if result.returncode == 0:
                if " is owned by " in stdout:
                    _, owner_part = stdout.split(" is owned by ", 1)
                    pkg = owner_part.strip().split()[0] if owner_part.strip() else ""
                    if pkg:
                        owners[path] = pkg
                elif " paketine ait" in stdout:
                    # Türkçe yerel: /path/to/file, pkg version paketine ait.
                    parts = stdout.split(",")
                    if len(parts) >= 2:
                        pkg = parts[1].strip().split()[0]
                        if pkg:
                            owners[path] = pkg
        return owners

    def _package_metadata(self, packages: list[str]) -> dict[str, dict]:
        if not packages:
            return {}
        result = self.runner.run(["env", "LC_ALL=C", "pacman", "-Qi", *packages], timeout=45)
        metadata: dict[str, dict] = {}
        current_pkg = ""
        current_data: dict = {}

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                if current_pkg and current_data:
                    metadata[current_pkg] = current_data
                current_pkg = ""
                current_data = {}
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if key == "name":
                current_pkg = val
                current_data = {}
            elif key == "version":
                current_data["version"] = val
            elif key == "installed size":
                current_data["size_kib"] = _parse_size_str(val)
            elif key == "install date":
                # Tarih formatını standartlaştır (örn: 'Sun 15 Nov 2026 ...' -> '2026-11-15')
                date_str = ""
                if val:
                    try:
                        # Pacman formatı: Sun 15 Nov 2026 05:30:12 PM ...
                        parts = val.split()
                        # Eğer format "Day DD Mon YYYY ..." şeklindeyse
                        if len(parts) >= 4 and len(parts[3]) == 4 and parts[3].isdigit():
                            from email.utils import parsedate_to_datetime
                            # RFC 2822 uyumlu parse denemesi
                            dt_str = f"{parts[0]}, {parts[1]} {parts[2]} {parts[3]} {parts[4]}"
                            dt = parsedate_to_datetime(dt_str)
                            date_str = dt.strftime("%Y-%m-%d")
                        else:
                            date_str = " ".join(parts[:4])
                    except Exception:
                        date_str = " ".join(val.split()[:4])
                current_data["install_date"] = date_str

        if current_pkg and current_data:
            metadata[current_pkg] = current_data
        return metadata

    def _upgradable_packages(self) -> dict[str, str]:
        if not self.runner.command_exists("pacman"):
            return {}
        # Arch/CachyOS'te root olmadan en güvenli güncelleme sorgusu 'checkupdates' aracıdır
        if self.runner.command_exists("checkupdates"):
            res = self.runner.run(["checkupdates"], timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                upgradable: dict[str, str] = {}
                for line in res.stdout.splitlines():
                    # Format: pkgname old_ver -> new_ver
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[2] == "->":
                        upgradable[parts[0]] = parts[3]
                if upgradable:
                    return upgradable

        # checkupdates yoksa veya boşsa standart pacman -Qu
        result = self.runner.run(["env", "LC_ALL=C", "pacman", "-Qu"], timeout=30)
        upgradable = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or " -> " not in line:
                continue
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "->":
                name = parts[0]
                new_ver = parts[3]
                upgradable[name] = new_ver
        return upgradable

    def list_all_packages(self, *, include_updates: bool = True) -> list[PackageInfo]:
        if not self.runner.command_exists("pacman"):
            return []
        # pacman -Q
        res = self.runner.run(["pacman", "-Q"], timeout=30)
        upgradable = self._upgradable_packages() if include_updates else {}
        packages: list[PackageInfo] = []
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                packages.append(
                    PackageInfo(
                        name=parts[0],
                        version=parts[1],
                        installed_size_kib=None,
                        description="",
                        update_available=parts[0] in upgradable,
                        new_version=upgradable.get(parts[0], ""),
                    )
                )
        return sorted(packages, key=lambda p: p.name)

    def search_store(self, query: str) -> list[StoreResult]:
        if not self.runner.command_exists("pacman"):
            return []
        try:
            # pacman -Ss <query>
            res = self.runner.run(["pacman", "-Ss", query], timeout=30)
            items: list[StoreResult] = []
            lines = res.stdout.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if "/" in line:
                    repo_pkg, version = line.split()[:2]
                    repo, pkg_name = repo_pkg.split("/", 1)
                    desc = lines[i + 1].strip() if (i + 1 < len(lines)) else ""
                    items.append(
                        StoreResult(
                            name=pkg_name,
                            app_id=pkg_name,
                            description=desc,
                            source=SOURCE_PACMAN,
                            version=version,
                            remote=repo,
                        )
                    )
                    i += 2
                else:
                    i += 1
            return items[:60]
        except Exception:
            return []

    def install_command(self, package: str) -> list[str]:
        return ["pacman", "-S", "--noconfirm", package]

    def update_command(self, package: str) -> list[str]:
        return ["pacman", "-S", "--noconfirm", package]

    def update_all_command(self) -> list[str]:
        return ["pacman", "-Syu", "--noconfirm"]

    def remove_command(self, package: str, purge: bool = False) -> list[str]:
        flag = "-Rns" if purge else "-R"
        return ["pacman", flag, "--noconfirm", package]

    def refresh_cache_command(self) -> list[str]:
        return ["pacman", "-Sy"]

    def get_lock_holders(self) -> list[tuple[str, str]]:
        holders: list[tuple[str, str]] = []
        lock_file = "/var/lib/pacman/db.lck"
        if os.path.exists(lock_file):
            holders.append(("lock_file", f"Veritabanı kilidi: {lock_file}"))
        try:
            res = self.runner.run(["pgrep", "-a", "-x", "pacman"], timeout=5)
            cur_pid = str(os.getpid())
            for line in res.stdout.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2 and parts[0] != cur_pid:
                    holders.append((parts[0], parts[1][:140]))
        except Exception:
            pass
        return holders
