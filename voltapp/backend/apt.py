#!/usr/bin/env python3
"""APT (Debian/Ubuntu/Zorin) paket yöneticisi sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import glob
import gzip
import os
from pathlib import Path

from voltapp.core.models import (
    SOURCE_APT,
    PackageInfo,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
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


class AptProvider:
    """Sistemdeki APT ve DPKG paketlerini yöneten ve listeleyen sağlayıcı."""

    source = SOURCE_APT

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner
        self._hidden_upgradable: set[str] = set()

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.runner.command_exists("dpkg-query"):
            return []

        desktop_entries = [
            entry
            for entry in self.scanner.list_entries(["/usr/share/applications", os.path.expanduser("~/.local/share/applications")])
            if entry.visible and not _entry_has_non_apt_source(entry)
        ]
        if not desktop_entries:
            return []

        owners = self._owning_packages([entry.path for entry in desktop_entries])
        if not owners:
            return []

        package_meta = self._package_metadata(sorted(set(owners.values())))
        upgradable = self._upgradable_packages()
        installed_dates, last_updated_dates = self._collect_package_dates(sorted(set(owners.values())))
        listed_packages: set[str] = set()
        applications: list[UnifiedApplication] = []
        for entry in desktop_entries:
            package = owners.get(entry.path)
            if not package:
                continue
            listed_packages.add(package)
            version, installed_size_kib = package_meta.get(package, ("", None))
            applications.append(
                UnifiedApplication(
                    id=f"{SOURCE_APT}:{package}:{Path(entry.path).name}",
                    name=entry.name,
                    source=SOURCE_APT,
                    version=version,
                    icon=entry.icon or "application-x-executable",
                    executable=_clean_exec_command(entry.exec_command),
                    desktop_file=entry.path,
                    install_path=str(Path(entry.path).parent),
                    category=_first_category(entry.categories),
                    package_name=package,
                    update_available=package in upgradable,
                    installed_size_kib=installed_size_kib,
                    installed_date=installed_dates.get(package, ""),
                    last_updated=last_updated_dates.get(package, ""),
                )
            )
        self._hidden_upgradable = upgradable - listed_packages
        return applications

    def _owning_packages(self, paths: list[str]) -> dict[str, str]:
        result = self.runner.run(["dpkg-query", "-S", *paths], timeout=30)
        owners: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            package_part, owned_path = line.split(":", 1)
            package = package_part.split(",", 1)[0].strip().split(":", 1)[0]
            path = owned_path.strip()
            if package and path:
                owners[path] = package
        return owners

    def _package_metadata(self, packages: list[str]) -> dict[str, tuple[str, int | None]]:
        if not packages:
            return {}
        result = self.runner.run(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Installed-Size}\n", *packages],
            timeout=30,
        )
        metadata: dict[str, tuple[str, int | None]] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            package = parts[0].split(":", 1)[0]
            version = parts[1]
            size = _safe_int(parts[2]) if len(parts) > 2 else None
            if size is None or size == 0:
                size = self._calc_package_disk_size(package)
            metadata[package] = (version, size)
        return metadata

    def _calc_package_disk_size(self, package: str) -> int | None:
        for suffix in ("", ":amd64", ":arm64", ":i386"):
            list_file = f"/var/lib/dpkg/info/{package}{suffix}.list"
            if os.path.exists(list_file):
                total_bytes = 0
                try:
                    with open(list_file, "r", encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            p = line.strip()
                            if p and os.path.isfile(p) and not os.path.islink(p):
                                try:
                                    total_bytes += os.path.getsize(p)
                                except OSError:
                                    pass
                    if total_bytes > 0:
                        return total_bytes // 1024
                except Exception:
                    pass
        return None

    def _upgradable_packages(self) -> set[str]:
        if not self.runner.command_exists("apt"):
            return set()
        result = self.runner.run(["apt", "list", "--upgradable", "-q"], timeout=30)
        packages: set[str] = set()
        for line in (result.stdout + result.stderr).splitlines():
            if "/" not in line:
                continue
            name = line.split("/", 1)[0].strip()
            if name and not name.lower().startswith("warning") and not name.lower().startswith("listing"):
                packages.add(name)
        return packages

    def _get_system_install_date(self) -> str:
        for p in ("/var/log/installer/media-info", "/var/log/installer"):
            if os.path.exists(p):
                try:
                    return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
                except OSError:
                    pass
        return ""

    def _parse_dpkg_history(self) -> tuple[dict[str, str], dict[str, str]]:
        first_installed: dict[str, str] = {}
        last_updated: dict[str, str] = {}

        log_files = glob.glob("/var/log/dpkg.log*")
        def _sort_key(fn: str) -> int:
            suffix = fn.split("dpkg.log")[-1].lstrip(".")
            if not suffix:
                return 0
            num = suffix.split(".")[0]
            try:
                return int(num)
            except ValueError:
                return 999

        # En eski log dosyasından en yeniye doğru tara
        log_files.sort(key=_sort_key, reverse=True)

        for fn in log_files:
            try:
                fh = gzip.open(fn, "rt", encoding="utf-8", errors="ignore") if fn.endswith(".gz") else open(fn, "rt", encoding="utf-8", errors="ignore")
                with fh:
                    for line in fh:
                        parts = line.split()
                        if len(parts) >= 4:
                            date_str = parts[0]
                            action = parts[2]
                            if action in ("install", "upgrade", "status"):
                                pkg = parts[3].split(":")[0]
                                if action == "install" and pkg not in first_installed:
                                    first_installed[pkg] = date_str
                                if action in ("install", "upgrade"):
                                    last_updated[pkg] = date_str
            except Exception:
                pass

        return first_installed, last_updated

    def _collect_package_dates(self, packages: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        if not packages:
            return {}, {}

        dpkg_first, dpkg_last = self._parse_dpkg_history()
        sys_install_date = self._get_system_install_date()

        # Dpkg .list mtime'ları son güncelleme için kesin referanstır
        paths = []
        for pkg in packages:
            for suffix in ("", ":amd64", ":arm64", ":i386"):
                paths.append(f"/var/lib/dpkg/info/{pkg}{suffix}.list")

        result = self.runner.run(["stat", "-c", "%n\t%Y", *paths], timeout=20)
        path_times: dict[str, int] = {}
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            path_part, ts_part = line.split("\t", 1)
            try:
                path_times[path_part.strip()] = int(ts_part.strip())
            except ValueError:
                pass

        installed_dates: dict[str, str] = {}
        last_updated_dates: dict[str, str] = {}

        for pkg in packages:
            file_mtime_date = ""
            for suffix in ("", ":amd64", ":arm64", ":i386"):
                key = f"/var/lib/dpkg/info/{pkg}{suffix}.list"
                if key in path_times:
                    file_mtime_date = datetime.fromtimestamp(path_times[key]).strftime("%Y-%m-%d")
                    break

            # Son güncelleme: .list mtime'ı veya dpkg logundaki son upgrade/install
            last_updated_dates[pkg] = file_mtime_date or dpkg_last.get(pkg, "")

            # İlk kurulum: dpkg logundaki install tarihi; yoksa sistem kurulum tarihi veya .list mtime
            if pkg in dpkg_first:
                installed_dates[pkg] = dpkg_first[pkg]
            elif sys_install_date:
                installed_dates[pkg] = sys_install_date
            else:
                installed_dates[pkg] = file_mtime_date

        return installed_dates, last_updated_dates

    def _upgradable_packages_with_versions(self) -> dict[str, str]:
        if not self.runner.command_exists("apt"):
            return {}
        result = self.runner.run(["apt", "list", "--upgradable", "-q"], timeout=30)
        versions: dict[str, str] = {}
        for line in (result.stdout + result.stderr).splitlines():
            if "/" not in line:
                continue
            name = line.split("/", 1)[0].strip()
            if not name or name.lower().startswith("warning") or name.lower().startswith("listing"):
                continue
            parts = line.split()
            new_ver = parts[1] if len(parts) >= 2 else ""
            if name and new_ver:
                versions[name] = new_ver
        return versions

    def list_all_packages(self) -> list[PackageInfo]:
        if not self.runner.command_exists("dpkg-query"):
            return []
        result = self.runner.run(
            [
                "dpkg-query", "-W",
                "-f=${binary:Package}\t${Version}\t${Installed-Size}\t${binary:Summary}\t${db:Status-Status}\n",
            ],
            timeout=60,
        )
        packages: dict[str, PackageInfo] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            name, version, size_str, description, status = (
                parts[0], parts[1], parts[2], parts[3], parts[4].strip()
            )
            if status != "installed":
                continue
            packages[name] = PackageInfo(
                name=name,
                version=version,
                installed_size_kib=_safe_int(size_str),
                description=description,
                update_available=False,
                new_version="",
            )
        upgradable = self._upgradable_packages_with_versions()
        for name, new_ver in upgradable.items():
            if name in packages:
                packages[name].update_available = True
                packages[name].new_version = new_ver
        return sorted(packages.values(), key=lambda p: p.name)

