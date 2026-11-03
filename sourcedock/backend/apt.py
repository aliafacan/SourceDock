#!/usr/bin/env python3
"""APT (Debian/Ubuntu/Zorin) paket yöneticisi sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import bz2
import glob
import gzip
import lzma
import os
from pathlib import Path
import re

from sourcedock.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    SOURCE_APT,
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.base_native import BaseNativeProvider
from sourcedock.core.errors import BackendError
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


_APT_UPGRADABLE_LINE = re.compile(
    r"^(?P<name>[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?)/\S+\s+"
    r"(?P<version>\S+)(?:\s+|$)",
    re.IGNORECASE,
)


def _base_package_name(name: str) -> str:
    """Return the Debian source name without discarding normal name punctuation."""
    return name.rsplit(":", 1)[0] if ":" in name else name


def _parse_apt_upgradable_output(output: str) -> dict[str, str]:
    """Parse machine-shaped fields from ``apt list --upgradable`` output.

    Headers and warnings are deliberately ignored instead of matching their
    translated prose. A slash-bearing package row is structural and must be
    valid; otherwise the inventory is incomplete and must not look like zero
    updates.
    """
    rows: list[tuple[str, str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "/" not in line:
            continue
        match = _APT_UPGRADABLE_LINE.match(line)
        if not match:
            raise BackendError(f"APT güncelleme çıktısı ayrıştırılamadı: {line[:200]}")
        fields = line.split()
        architecture = fields[2] if len(fields) >= 3 else ""
        rows.append((match.group("name"), match.group("version"), architecture))
    versions: dict[str, str] = {}
    duplicate_names = {
        name for name, _version, _architecture in rows
        if sum(candidate == name for candidate, _v, _a in rows) > 1
    }
    for name, version, architecture in rows:
        key = f"{name}:{architecture}" if name in duplicate_names and ":" not in name and architecture else name
        versions[key] = version
    return versions


def _parse_dpkg_history_lines(lines) -> tuple[dict[str, str], dict[str, str]]:
    """Parse dpkg events and retain dates for the current installation.

    A package can be installed, removed, and installed again. Tracking only
    the first ``install`` event makes a reinstall look as if it happened on
    the original installation date, so remove/purge events clear that state.
    """

    installed_at: dict[str, str] = {}
    last_updated: dict[str, str] = {}
    # Rotated logs can overlap and glob order is not guaranteed. dpkg's
    # timestamp is ISO-like, so a stable lexical ordering is chronological.
    ordered_lines = sorted(enumerate(lines), key=lambda item: (" ".join(item[1].split()[:2]), item[0]))
    for _index, line in ordered_lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        date_str = parts[0]
        action = parts[2]
        pkg = parts[3]
        if not pkg:
            continue
        if action == "install":
            # dpkg normally records upgrades as ``upgrade``, but some local
            # package installs are logged as ``install <old> <new>``. Keep
            # the original date when the versions differ; only a fresh
            # install or same-version reinstall starts a new installation.
            old_version = parts[4] if len(parts) > 5 else "<none>"
            new_version = parts[5] if len(parts) > 5 else parts[4]
            if old_version not in ("", "<none>") and old_version != new_version:
                last_updated[pkg] = date_str
            else:
                installed_at[pkg] = date_str
                last_updated[pkg] = date_str
        elif action in ("remove", "purge"):
            installed_at.pop(pkg, None)
            last_updated.pop(pkg, None)
        elif action == "upgrade":
            last_updated[pkg] = date_str
    for history in (installed_at, last_updated):
        bases: dict[str, list[str]] = {}
        for package in list(history):
            bases.setdefault(_base_package_name(package), []).append(package)
        for base, qualified in bases.items():
            if base not in history and len(qualified) == 1:
                history[base] = history[qualified[0]]
    return installed_at, last_updated


class AptProvider(BaseNativeProvider):
    """Sistemdeki APT ve DPKG paketlerini yöneten ve listeleyen sağlayıcı."""

    source = SOURCE_APT
    display_name = "APT"

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        super().__init__(runner, scanner)
        self._last_update_query_error = ""

    def is_available(self) -> bool:
        return self.runner.command_exists("dpkg-query") or self.runner.command_exists("apt")

    def list_applications(self, *, include_updates: bool = True) -> list[UnifiedApplication]:
        if not self.runner.command_exists("dpkg-query"):
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

        try:
            owners = self._owning_packages([entry.path for entry in desktop_entries])
        except (BackendError, OSError):
            return []
        if not owners:
            return []

        packages = sorted(set(owners.values()))
        try:
            package_meta = self._package_metadata(packages)
        except (BackendError, OSError):
            package_meta = {}
        if include_updates:
            try:
                upgradable = self._upgradable_packages()
                self._last_update_query_error = ""
            except (BackendError, OSError) as exc:
                self._last_update_query_error = str(exc)
                upgradable = set()
        else:
            self._last_update_query_error = ""
            upgradable = set()
        # Dpkg history and the stat fan-out are secondary metadata. They are
        # intentionally skipped by the fast installed-app inventory and are
        # populated by the regular update/details paths when needed.
        if include_updates:
            try:
                installed_dates, last_updated_dates = self._collect_package_dates(packages)
            except (BackendError, OSError):
                installed_dates, last_updated_dates = {}, {}
        else:
            installed_dates, last_updated_dates = {}, {}
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
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"dpkg dosya sahipliği sorgusu başarısız: {detail}")
        owners: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ": " not in line:
                continue
            package_part, owned_path = line.split(": ", 1)
            package = package_part.split(",", 1)[0].strip()
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
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"dpkg paket bilgisi sorgusu başarısız: {detail}")
        metadata: dict[str, tuple[str, int | None]] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            package = parts[0]
            version = parts[1]
            size = _safe_int(parts[2]) if len(parts) > 2 else None
            if size is None or size == 0:
                size = self._calc_package_disk_size(package)
            metadata[package] = (version, size)
        return metadata

    def _calc_package_disk_size(self, package: str) -> int | None:
        suffixes = ("",) if ":" in package else ("", ":amd64", ":arm64", ":i386")
        for suffix in suffixes:
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
        return set(self._upgradable_packages_with_versions())

    def _get_system_install_date(self) -> str:
        for p in ("/var/log/installer/media-info", "/var/log/installer"):
            if os.path.exists(p):
                try:
                    return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
                except OSError:
                    pass
        return ""

    def _parse_dpkg_history(self) -> tuple[dict[str, str], dict[str, str]]:
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

        all_lines = []
        for fn in log_files:
            try:
                if fn.endswith(".gz"):
                    fh = gzip.open(fn, "rt", encoding="utf-8", errors="ignore")
                elif fn.endswith(".bz2"):
                    fh = bz2.open(fn, "rt", encoding="utf-8", errors="ignore")
                elif fn.endswith((".xz", ".lzma")):
                    fh = lzma.open(fn, "rt", encoding="utf-8", errors="ignore")
                else:
                    fh = open(fn, "rt", encoding="utf-8", errors="ignore")
                with fh:
                    all_lines.extend(fh)
            except Exception:
                pass

        return _parse_dpkg_history_lines(all_lines)

    def _collect_package_dates(self, packages: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        if not packages:
            return {}, {}

        dpkg_installed, dpkg_last = self._parse_dpkg_history()

        installed_dates: dict[str, str] = {}
        last_updated_dates: dict[str, str] = {}

        def history_value(history: dict[str, str], package: str) -> str:
            if package in history:
                return history[package]
            base = _base_package_name(package)
            matches = [value for key, value in history.items() if _base_package_name(key) == base]
            return matches[0] if len(matches) == 1 else ""

        for pkg in packages:
            # Only dpkg actions are verified evidence. Both .list and desktop
            # mtimes are rewritten by upgrades and therefore cannot establish
            # the start of the current installation instance.
            installed_dates[pkg] = history_value(dpkg_installed, pkg)
            last_updated_dates[pkg] = history_value(dpkg_last, pkg)

        return installed_dates, last_updated_dates

    def _upgradable_packages_with_versions(self) -> dict[str, str]:
        if not self.runner.command_exists("apt"):
            raise BackendError("APT güncelleme sorgusu kullanılamıyor: apt komutu bulunamadı.")
        result = self.runner.run(
            ["apt", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "list", "--upgradable", "-q"],
            timeout=45,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"APT güncelleme sorgusu başarısız (kod {result.returncode}): {detail}")
        return _parse_apt_upgradable_output(result.stdout)

    def list_all_packages(self) -> list[PackageInfo]:
        if not self.runner.command_exists("dpkg-query"):
            return []
        result = self.runner.run(
            [
                "dpkg-query",
                "-W",
                "-f=${binary:Package}\t${Version}\t${Installed-Size}\t${binary:Summary}\t${db:Status-Status}\n",
            ],
            timeout=60,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"Kurulu APT paketleri okunamadı (kod {result.returncode}): {detail}")
        packages: dict[str, PackageInfo] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            name, version, size_str, description, status = (
                parts[0],
                parts[1],
                parts[2],
                parts[3],
                parts[4].strip(),
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
            package = packages.get(name)
            if package is None and ":" not in name:
                matches = [item for key, item in packages.items() if _base_package_name(key) == name]
                package = matches[0] if len(matches) == 1 else None
            if package is not None:
                package.update_available = True
                package.new_version = new_ver
            else:
                raise BackendError(
                    f"APT {name} paketini güncellenebilir bildirdi ancak kurulu dpkg envanterinde eşleşme bulunamadı."
                )
        return sorted(packages.values(), key=lambda p: p.name)

    def search_store(self, query: str) -> list[StoreResult]:
        if not self.runner.command_exists("apt-cache"):
            return []
        try:
            res = self.runner.run(["apt-cache", "search", "--", query], timeout=30)
            items: list[StoreResult] = []
            pkg_names: list[str] = []
            raw_results: list[tuple[str, str]] = []
            for line in res.stdout.splitlines():
                if " - " not in line:
                    continue
                pkg_name, description = line.split(" - ", 1)
                pkg_name = pkg_name.strip()
                description = description.strip()
                if not pkg_name:
                    continue
                raw_results.append((pkg_name, description))
                pkg_names.append(pkg_name)
            raw_results = raw_results[:60]
            pkg_names = pkg_names[:60]

            versions: dict[str, str] = {}
            if pkg_names:
                try:
                    policy_res = self.runner.run(["apt-cache", "policy", "--", *pkg_names], timeout=30)
                    cur_pkg = ""
                    for p_line in policy_res.stdout.splitlines():
                        s = p_line.strip()
                        if not p_line.startswith(" ") and s.endswith(":"):
                            cur_pkg = s[:-1]
                        elif cur_pkg and s.startswith("Candidate:"):
                            c_ver = s.split(":", 1)[1].strip()
                            if c_ver and c_ver != "(none)":
                                versions[cur_pkg] = c_ver
                except Exception:
                    pass

            for pkg_name, description in raw_results:
                items.append(
                    StoreResult(
                        name=pkg_name,
                        app_id=pkg_name,
                        description=description,
                        source=SOURCE_APT,
                        version=versions.get(pkg_name, ""),
                        remote="apt",
                    )
                )
            return items
        except Exception:
            return []

    def install_command(self, package: str) -> list[str]:
        return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "install", "-y", package]

    def update_command(self, package: str) -> list[str]:
        return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "install", "--only-upgrade", "-y", package]

    def update_all_command(self) -> list[str]:
        if self.runner.command_exists("nala"):
            return ["nala", "upgrade", "-y"]
        return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "upgrade", "-y"]

    def remove_command(self, package: str, purge: bool = False) -> list[str]:
        cmd = "purge" if purge else "remove"
        return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, cmd, "-y", package]

    def refresh_cache_command(self) -> list[str]:
        return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "update", "-q"]

    def get_lock_holders(self) -> list[tuple[str, str]]:
        script = r"""
locks="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock"
pids=""
if command -v fuser >/dev/null 2>&1; then
  for lock in $locks; do
    [ -e "$lock" ] || continue
    found="$(fuser "$lock" 2>/dev/null || true)"
    pids="$pids $found"
  done
fi
pids="$(printf '%s\n' $pids | awk '!seen[$1]++')"
if [ -n "$pids" ]; then
  ps -p "$(printf '%s,' $pids | sed 's/,$//')" -o pid=,args= 2>/dev/null || true
else
  ps -eo pid=,args= | awk '/[a]pt |[a]pt-get |[d]pkg |[u]nattended-upgrade/ && !/wait-for-signal/ {print}'
fi
"""
        try:
            res = self.runner.run(["sh", "-lc", script], timeout=5)
        except Exception:
            return []
        holders: list[tuple[str, str]] = []
        current_pid = str(os.getpid())
        for line in res.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid, args = parts
            if pid == current_pid:
                continue
            lowered = args.lower()
            if not any(token in lowered for token in ("apt", "apt-get", "dpkg", "unattended-upgrade")):
                continue
            holders.append((pid, args[:140]))
        return holders
