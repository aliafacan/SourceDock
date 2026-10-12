#!/usr/bin/env python3
"""Unified installed applications registry and package providers."""

from __future__ import annotations

from collections.abc import Callable
from configparser import ConfigParser
from dataclasses import dataclass, field
from datetime import datetime
import glob
import locale
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

from backend import AuthRequiredError, BackendError


SOURCE_APT = "apt"
SOURCE_FLATPAK = "flatpak"
SOURCE_SNAP = "snap"
SOURCE_APPIMAGE = "appimage"

PACKAGE_MANAGER_SOURCES = {SOURCE_APT, SOURCE_FLATPAK, SOURCE_SNAP}
APT_LOCK_NOWAIT = "-o"
APT_LOCK_NOWAIT_VALUE = "DPkg::Lock::Timeout=0"
APT_LOCK_PATHS = (
    "/var/lib/dpkg/lock-frontend",
    "/var/lib/dpkg/lock",
    "/var/cache/apt/archives/lock",
    "/var/lib/apt/lists/lock",
)
DESKTOP_DIRS = [
    "/usr/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
]


@dataclass(frozen=True)
class UnifiedApplication:
    id: str
    name: str
    source: str
    version: str = ""
    icon: str = ""
    executable: str = ""
    desktop_file: str = ""
    install_path: str = ""
    category: str = ""
    package_name: str = ""
    update_available: bool = False
    installed_size_kib: int | None = None
    update_supported: bool = True
    update_note: str = ""
    last_updated: str = ""


@dataclass(frozen=True)
class ApplicationIssue:
    kind: str
    title: str
    detail: str = ""
    path: str = ""


@dataclass
class PackageInfo:
    name: str
    version: str
    installed_size_kib: int | None
    description: str
    update_available: bool
    new_version: str = ""


@dataclass(frozen=True)
class ApplicationSnapshot:
    applications: list[UnifiedApplication]
    issues: list[ApplicationIssue] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DesktopEntry:
    path: str
    name: str
    icon: str
    exec_command: str
    categories: str
    no_display: bool
    hidden: bool
    terminal: bool
    flatpak_id: str
    snap_name: str
    appimage_path: str
    appimage_update_info: str

    @property
    def visible(self) -> bool:
        return bool(self.name and self.exec_command and not self.no_display and not self.hidden and not self.terminal)


class CommandRunner:
    def __init__(self):
        self.host_bridge_available = self._detect_host_bridge()
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self._current_process: subprocess.Popen | None = None

    def cancel_current(self) -> None:
        proc = self._current_process
        if proc and proc.poll() is None:
            proc.terminate()

    def set_sudo_password(self, password: str) -> None:
        self._sudo_password = password

    def clear_sudo_password(self) -> None:
        self._sudo_password = None

    def set_output_callback(self, callback: Callable[[str], None] | None) -> None:
        self._output_callback = callback

    def command_exists(self, command: str) -> bool:
        if self.host_bridge_available:
            result = self.run(["sh", "-lc", f"command -v {shlex.quote(command)} >/dev/null 2>&1"], timeout=5)
            return result.returncode == 0
        return shutil.which(command) is not None

    def path_exists(self, path: str) -> bool:
        if self.host_bridge_available:
            result = self.run(["test", "-e", path], timeout=5)
            return result.returncode == 0
        return os.path.exists(path)

    def read_text(self, path: str) -> str:
        if self.host_bridge_available and self.path_exists(path):
            result = self.run(["cat", path], timeout=10, check=True)
            return result.stdout

        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def list_desktop_files(self, directories: list[str]) -> list[str]:
        if self.host_bridge_available:
            script = (
                'for dir in "$@"; do '
                '[ -d "$dir" ] && find "$dir" -maxdepth 1 -type f -name "*.desktop"; '
                "done"
            )
            result = self.run(["sh", "-c", script, "desktop-scan", *directories], timeout=15)
            if result.returncode == 0:
                return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})

        paths: list[str] = []
        for directory in directories:
            root = Path(directory).expanduser()
            if not root.exists():
                continue
            paths.extend(str(item) for item in root.glob("*.desktop") if item.is_file())
        return sorted(set(paths))

    def run(
        self,
        command: list[str],
        timeout: int = 30,
        check: bool = False,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        wrapped = self._wrap_host(command)
        if self._output_callback is not None and timeout >= 120:
            return self._run_streaming(wrapped, timeout, check, stdin_text=input_text)
        try:
            result = subprocess.run(
                wrapped,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(f"Komut calistirilamadi: {' '.join(command)}\n{exc}") from exc

        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}")
        return result

    def _run_streaming(
        self,
        wrapped_command: list[str],
        timeout: int,
        check: bool,
        stdin_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run command with real-time output via _output_callback."""
        try:
            process = subprocess.Popen(
                wrapped_command,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._current_process = process
            if stdin_text is not None:
                try:
                    encoded = stdin_text.encode("utf-8")
                    process.stdin.write(encoded)  # type: ignore[union-attr]
                    process.stdin.flush()  # type: ignore[union-attr]
                    process.stdin.close()  # type: ignore[union-attr]
                except OSError:
                    pass
            collected: list[str] = []
            buf = b""
            while True:
                chunk = process.stdout.read(256)  # type: ignore[union-attr]
                if not chunk:
                    break
                buf += chunk
                while True:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        idx = buf.find(sep)
                        if idx >= 0:
                            line = buf[:idx].decode("utf-8", errors="replace").strip()
                            buf = buf[idx + len(sep):]
                            if line:
                                collected.append(line)
                                if self._output_callback is not None:
                                    self._output_callback(line)
                            break
                    else:
                        break
            if buf:
                line = buf.decode("utf-8", errors="replace").strip()
                if line:
                    collected.append(line)
                    if self._output_callback is not None:
                        self._output_callback(line)
            try:
                process.wait(timeout=max(5, timeout - 5))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise BackendError("Komut zaman asimina ugradi.")
            result = subprocess.CompletedProcess(
                args=wrapped_command,
                returncode=process.returncode,
                stdout="\n".join(collected),
                stderr="",
            )
            self._current_process = None
            if check and result.returncode != 0:
                tail = "\n".join(collected[-3:])
                raise BackendError(f"Komut basarisiz oldu: {' '.join(wrapped_command)}\n{tail}")
            return result
        except OSError as exc:
            self._current_process = None
            raise BackendError(f"Komut calistirilamadi: {' '.join(wrapped_command)}\n{exc}") from exc

    def run_privileged(
        self,
        command: list[str],
        timeout: int = 900,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._wait_for_apt_locks(command)
        sudo_probe = self.run(["sudo", "-n", "true"], timeout=5)
        if sudo_probe.returncode == 0:
            result = self.run(["sudo", "-n", *command], timeout=timeout, input_text=input_text)
            self._raise_for_privileged_result(result, command)
            return result

        if not self._sudo_password:
            raise AuthRequiredError(
                "Yonetici parolasi gerekiyor. Canli onizlemeyi uygulama icinden acmak icin parolayi gir.",
            )

        stdin_text = f"{self._sudo_password}\n"
        if input_text is not None:
            stdin_text += input_text

        result = self.run(["sudo", "-S", "-p", "", *command], timeout=timeout, input_text=stdin_text)
        self._raise_for_privileged_result(result, command)
        return result

    def _raise_for_privileged_result(
        self,
        result: subprocess.CompletedProcess[str],
        command: list[str],
    ) -> None:
        if result.returncode != 0:
            combined = ((result.stderr or "") + "\n" + (result.stdout or "")).strip().lower()
            if any(kw in combined for kw in ("password", "try again", "incorrect", "sorry")):
                self.clear_sudo_password()
                raise AuthRequiredError(
                    "Yonetici parolasi hatali. Lutfen tekrar dene.",
                    password_failed=True,
                )
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}")

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        started = time.monotonic()
        last_message = ""
        while True:
            holders = self._apt_lock_holders()
            if not holders:
                if last_message and self._output_callback is not None:
                    self._output_callback("APT kilidi boşaldı. İşleme devam ediliyor...")
                return
            summary = "; ".join(f"PID {pid}: {args}" for pid, args in holders[:3])
            if len(holders) > 3:
                summary += f"; +{len(holders) - 3} işlem"
            message = f"APT meşgul: {summary}"
            if message != last_message and self._output_callback is not None:
                self._output_callback(message)
                self._output_callback("Diğer APT işlemi bitince otomatik devam edilecek...")
                last_message = message
            if time.monotonic() - started >= max_wait:
                raise BackendError(f"APT şu anda başka bir işlem tarafından kullanılıyor.\n{summary}")
            time.sleep(2)

    def _apt_lock_holders(self) -> list[tuple[str, str]]:
        script = r'''
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
'''
        try:
            result = self.run(["sh", "-lc", script], timeout=5)
        except Exception:
            return []
        holders: list[tuple[str, str]] = []
        current_pid = str(os.getpid())
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid, args = parts
            if pid == current_pid:
                continue
            lowered = args.lower()
            if not any(token in lowered for token in ("apt", "apt-get", "dpkg", "unattended-upgrade")):
                continue
            if "wait-for-signal" in lowered:
                continue
            holders.append((pid, args[:140]))
        return holders

    def spawn(self, command: list[str]) -> None:
        try:
            subprocess.Popen(
                self._wrap_host(command),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise BackendError(f"Komut calistirilamadi: {' '.join(command)}\n{exc}") from exc

    def _wrap_host(self, command: list[str]) -> list[str]:
        if self.host_bridge_available:
            return ["flatpak-spawn", "--host", *command]
        return command

    def _detect_host_bridge(self) -> bool:
        if not shutil.which("flatpak-spawn"):
            return False

        result = subprocess.run(
            ["flatpak-spawn", "--host", "true"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0


class DesktopEntryScanner:
    def __init__(self, runner: CommandRunner):
        self.runner = runner
        self._locale = (locale.getlocale()[0] or "").replace("-", "_")

    def list_entries(self, directories: list[str] | None = None) -> list[DesktopEntry]:
        entries: list[DesktopEntry] = []
        for path in self.runner.list_desktop_files(directories or DESKTOP_DIRS):
            entry = self.load_entry(path)
            if entry is not None:
                entries.append(entry)
        return entries

    def load_entry(self, path: str) -> DesktopEntry | None:
        parser = ConfigParser(interpolation=None)
        parser.optionxform = str
        try:
            parser.read_string(self.runner.read_text(path))
        except (OSError, BackendError, ValueError):
            return None

        if "Desktop Entry" not in parser:
            return None

        section = parser["Desktop Entry"]
        if section.get("Type", "Application") != "Application":
            return None

        exec_command = section.get("Exec", "").strip()
        return DesktopEntry(
            path=path,
            name=self._localized_value(section, "Name") or Path(path).stem,
            icon=section.get("Icon", "").strip(),
            exec_command=exec_command,
            categories=section.get("Categories", "").strip(),
            no_display=_truthy(section.get("NoDisplay", "")),
            hidden=_truthy(section.get("Hidden", "")),
            terminal=_truthy(section.get("Terminal", "")),
            flatpak_id=section.get("X-Flatpak", "").strip(),
            snap_name=section.get("X-SnapInstanceName", "").strip(),
            appimage_path=_extract_appimage_path(exec_command),
            appimage_update_info=section.get("X-AppImage-UpdateInformation", "").strip(),
        )

    def _localized_value(self, section, key: str) -> str:
        locale_keys = []
        if self._locale:
            locale_keys.append(f"{key}[{self._locale}]")
            if "_" in self._locale:
                locale_keys.append(f"{key}[{self._locale.split('_', 1)[0]}]")
        locale_keys.append(key)

        for locale_key in locale_keys:
            value = section.get(locale_key, "").strip()
            if value:
                return value
        return ""


class ApplicationProvider:
    source = ""

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner

    def list_applications(self) -> list[UnifiedApplication]:
        raise NotImplementedError


class AptProvider(ApplicationProvider):
    source = SOURCE_APT

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
        install_dates = self._install_dates(sorted(set(owners.values())))
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
                    last_updated=install_dates.get(package, ""),
                )
            )
        # Track hidden (system) upgradable packages for informational display
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
            metadata[package] = (version, size)
        return metadata

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

    def _install_dates(self, packages: list[str]) -> dict[str, str]:
        """Get install/upgrade dates from dpkg info file mtimes (batch stat call)."""
        if not packages:
            return {}
        paths = []
        pkg_to_path: dict[str, str] = {}
        for pkg in packages:
            for suffix in ("", ":amd64", ":arm64", ":i386"):
                candidate = f"/var/lib/dpkg/info/{pkg}{suffix}.list"
                paths.append(candidate)
                if pkg not in pkg_to_path:
                    pkg_to_path[pkg] = candidate  # first candidate as default

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

        dates: dict[str, str] = {}
        for pkg in packages:
            for suffix in ("", ":amd64", ":arm64", ":i386"):
                key = f"/var/lib/dpkg/info/{pkg}{suffix}.list"
                if key in path_times:
                    dates[pkg] = datetime.fromtimestamp(path_times[key]).strftime("%Y-%m-%d")
                    break
        return dates

    def _upgradable_packages_with_versions(self) -> dict[str, str]:
        """Return {pkg_name: new_version} for all upgradable packages."""
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
        """Return all installed dpkg packages with metadata and update info."""
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


class FlatpakProvider(ApplicationProvider):
    source = SOURCE_FLATPAK

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.runner.command_exists("flatpak"):
            return []

        result = self.runner.run(
            ["flatpak", "list", "--app", "--columns=application,name,version,origin,installation,size"],
            timeout=30,
        )
        has_size_col = result.returncode == 0
        if not has_size_col:
            result = self.runner.run(
                ["flatpak", "list", "--app", "--columns=application,name,version,origin,installation"],
                timeout=30,
            )
            if result.returncode != 0:
                return []

        update_ids = self._update_ids()
        desktop_entries = {Path(entry.path).stem: entry for entry in self.scanner.list_entries(_flatpak_desktop_dirs())}
        applications: list[UnifiedApplication] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            app_id = parts[0].strip()
            name = parts[1].strip() or app_id
            version = parts[2].strip() if len(parts) > 2 else ""
            installation = parts[4].strip() if len(parts) > 4 else "system"
            installed_size_kib = _parse_human_size_kib(parts[5].strip()) if has_size_col and len(parts) > 5 else None
            entry = desktop_entries.get(app_id)
            if entry and not entry.visible:
                continue
            install_path = _flatpak_install_path(app_id, installation)
            applications.append(
                UnifiedApplication(
                    id=f"{SOURCE_FLATPAK}:{app_id}",
                    name=entry.name if entry else name,
                    source=SOURCE_FLATPAK,
                    version=version,
                    icon=(entry.icon if entry else app_id) or "application-x-executable",
                    executable=(entry.exec_command if entry else f"flatpak run {app_id}"),
                    desktop_file=entry.path if entry else _flatpak_desktop_path(app_id, installation),
                    install_path=install_path,
                    category=_first_category(entry.categories) if entry else "",
                    package_name=app_id,
                    update_available=app_id in update_ids,
                    installed_size_kib=installed_size_kib,
                    last_updated=_flatpak_last_updated(install_path),
                )
            )
        return applications

    def _update_ids(self) -> set[str]:
        result = self.runner.run(["flatpak", "remote-ls", "--updates", "--app", "--columns=application"], timeout=30)
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}


class SnapProvider(ApplicationProvider):
    source = SOURCE_SNAP

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.runner.command_exists("snap"):
            return []

        snaps = self._snap_metadata()
        if not snaps:
            return []

        update_names = self._update_names()
        applications: list[UnifiedApplication] = []
        seen_desktop_files: set[str] = set()
        for entry in self.scanner.list_entries(["/var/lib/snapd/desktop/applications", os.path.expanduser("~/.local/share/applications")]):
            if not entry.visible:
                continue
            snap_name = entry.snap_name or _snap_name_from_desktop(entry)
            if not snap_name or snap_name not in snaps:
                continue
            seen_desktop_files.add(entry.path)
            version = snaps[snap_name]
            applications.append(
                UnifiedApplication(
                    id=f"{SOURCE_SNAP}:{snap_name}:{Path(entry.path).name}",
                    name=entry.name,
                    source=SOURCE_SNAP,
                    version=version,
                    icon=entry.icon or "application-x-executable",
                    executable=entry.exec_command,
                    desktop_file=entry.path,
                    install_path=f"/snap/{snap_name}/current",
                    category=_first_category(entry.categories),
                    package_name=snap_name,
                    update_available=snap_name in update_names,
                )
            )

        return _dedupe_applications(applications, seen_desktop_files)

    def _snap_metadata(self) -> dict[str, str]:
        result = self.runner.run(["snap", "list"], timeout=30)
        if result.returncode != 0:
            return {}
        snaps: dict[str, str] = {}
        for index, line in enumerate(result.stdout.splitlines()):
            if index == 0 or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                snaps[parts[0]] = parts[1]
        return snaps

    def _update_names(self) -> set[str]:
        result = self.runner.run(["snap", "refresh", "--list"], timeout=30)
        if result.returncode != 0:
            return set()
        names: set[str] = set()
        for index, line in enumerate(result.stdout.splitlines()):
            if index == 0 or not line.strip() or line.lower().startswith("all snaps"):
                continue
            names.add(line.split()[0])
        return names


class AppImageProvider(ApplicationProvider):
    source = SOURCE_APPIMAGE

    def list_applications(self) -> list[UnifiedApplication]:
        appimage_update_available = self.runner.command_exists("AppImageUpdate")
        by_path: dict[str, UnifiedApplication] = {}

        for entry in self.scanner.list_entries([os.path.expanduser("~/.local/share/applications"), "/usr/share/applications"]):
            if not entry.visible or not entry.appimage_path:
                continue
            path = _normalize_path(entry.appimage_path)
            by_path[path] = self._application_from_path(path, entry, appimage_update_available)

        for path in self._scan_appimage_files():
            normalized_path = _normalize_path(path)
            if normalized_path in by_path:
                continue
            by_path[normalized_path] = self._application_from_path(normalized_path, None, appimage_update_available)

        return sorted(by_path.values(), key=lambda app: app.name.lower())

    def _application_from_path(
        self,
        path: str,
        entry: DesktopEntry | None,
        appimage_update_available: bool,
    ) -> UnifiedApplication:
        name = entry.name if entry else _name_from_appimage(path)
        update_info = entry.appimage_update_info if entry else ""
        update_supported = bool(appimage_update_available and update_info)
        size = None
        try:
            size = max(1, os.path.getsize(path) // 1024)
        except OSError:
            pass
        last_updated = ""
        try:
            last_updated = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        except OSError:
            pass

        return UnifiedApplication(
            id=f"{SOURCE_APPIMAGE}:{path}",
            name=name,
            source=SOURCE_APPIMAGE,
            version=_appimage_version(entry, path),
            icon=(entry.icon if entry else "") or "application-x-executable",
            executable=path,
            desktop_file=entry.path if entry else "",
            install_path=path,
            category=_first_category(entry.categories) if entry else "",
            package_name=path,
            update_available=False,
            installed_size_kib=size,
            update_supported=update_supported,
            update_note="" if update_supported else "manual",
            last_updated=last_updated,
        )

    def _scan_appimage_files(self) -> list[str]:
        candidates = [
            Path.home() / "Applications",
            Path.home() / "AppImages",
            Path.home() / "Downloads",
        ]
        paths: list[str] = []
        for root in candidates:
            if not root.exists():
                continue
            for current_root, dirs, files in os.walk(root):
                depth = len(Path(current_root).relative_to(root).parts)
                if depth >= 3:
                    dirs[:] = []
                dirs[:] = [item for item in dirs if not item.startswith(".")]
                for file_name in files:
                    if file_name.lower().endswith(".appimage"):
                        paths.append(str(Path(current_root) / file_name))
        return sorted(set(paths))


class ApplicationRegistry:
    def __init__(self):
        self.runner = CommandRunner()
        self.scanner = DesktopEntryScanner(self.runner)
        self.applications: list[UnifiedApplication] = []
        self.providers: list[ApplicationProvider] = [
            AptProvider(self.runner, self.scanner),
            FlatpakProvider(self.runner, self.scanner),
            SnapProvider(self.runner, self.scanner),
            AppImageProvider(self.runner, self.scanner),
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
        """Non-interactive update cache refresh — no sudo prompt. Safe to call on startup."""
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

        # Report hidden (no .desktop) APT upgrades as informational note
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
        """Return all installed APT packages (including headless/system ones)."""
        apt_provider = next((p for p in self.providers if isinstance(p, AptProvider)), None)
        if apt_provider is None:
            return []
        return apt_provider.list_all_packages()

    def update_packages(self, names: list[str]) -> None:
        """Upgrade the given APT packages by name."""
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
        raise BackendError("Bilinmeyen uygulama kaynagi.")

    def flatpak_cleanup(self) -> None:
        if self.runner.command_exists("flatpak"):
            self.runner.run(["flatpak", "uninstall", "--user", "--unused", "-y"], timeout=300, check=False)
            self.runner.run_privileged(["flatpak", "uninstall", "--system", "--unused", "-y"], timeout=300)

    def flatpak_history(self, app_id: str) -> list[dict]:
        """Return list of {commit, version, date} for a Flatpak app."""
        result = self.runner.run(
            ["flatpak", "remote-info", "--log", "flathub", app_id],
            timeout=30,
        )
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
        """Roll back a Flatpak app to a specific commit."""
        self.runner.run(
            ["flatpak", "update", "--commit", commit, "-y", app_id],
            timeout=1800,
            check=True,
        )

    def flatpak_permissions(self, app_id: str) -> dict[str, list[str]]:
        """Return current override permissions for a Flatpak app."""
        result = self.runner.run(
            ["flatpak", "override", "--show", app_id],
            timeout=10,
        )
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
        """Remove all user overrides for a Flatpak app."""
        self.runner.run(["flatpak", "override", "--reset", app_id], timeout=15, check=True)

    def export_app_list(self) -> str:
        """Return a JSON string of all installed apps (name, source, version, package_name)."""
        import json as _json
        data = [
            {
                "name": app.name,
                "source": app.source,
                "version": app.version,
                "package": app.package_name,
            }
            for app in self.applications
        ]
        return _json.dumps(data, ensure_ascii=False, indent=2)

    def apt_changelog(self, package_name: str) -> str:
        """Return changelog text for an APT package."""
        # Try reading compressed changelog directly (no pager, no network)
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
        # Fallback: uncompressed changelog
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
        """Copy AppImage to ~/Applications and create a .desktop launcher."""
        apps_dir = os.path.expanduser("~/Applications")
        os.makedirs(apps_dir, exist_ok=True)
        dest = os.path.join(apps_dir, os.path.basename(path))
        if os.path.abspath(path) != os.path.abspath(dest):
            import shutil as _shutil
            _shutil.copy2(path, dest)
        os.chmod(dest, 0o755)
        name = _name_from_appimage(dest)
        desktop_dir = os.path.expanduser("~/.local/share/applications")
        os.makedirs(desktop_dir, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name.lower())
        desktop_path = os.path.join(desktop_dir, f"appimage-{safe_name}.desktop")
        desktop_content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f"Exec={dest}\n"
            f"Icon=application-x-executable\n"
            "Categories=Utility;\n"
            f"X-AppImage-Path={dest}\n"
        )
        with open(desktop_path, "w", encoding="utf-8") as fh:
            fh.write(desktop_content)

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
            if len({application.source for application in group}) > 1:
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
        return len(candidate.name) > len(current.name)

    def _preference_sort_key(self, application: UnifiedApplication) -> tuple[int, int, int, str]:
        source_priority = {
            SOURCE_APT: 0,
            SOURCE_FLATPAK: 1,
            SOURCE_SNAP: 2,
            SOURCE_APPIMAGE: 3,
        }.get(application.source, 9)
        return (
            0 if application.update_available else 1,
            0 if application.desktop_file else 1,
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


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _apt_command(*args: str) -> list[str]:
    return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, *args]


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_human_size_kib(size_str: str) -> int | None:
    """Parse human-readable size like '582,1 MB' or '1.2 GB' to KiB."""
    parts = size_str.strip().split()
    if len(parts) != 2:
        return None
    try:
        num = float(parts[0].replace(",", "."))
    except ValueError:
        return None
    unit = parts[1].upper().rstrip("IB").rstrip("I")
    multipliers = {"B": 1.0 / 1024, "K": 1.0, "M": 1024.0, "G": 1024.0 * 1024, "T": 1024.0 * 1024 * 1024}
    mult = multipliers.get(unit[0] if unit else "")
    if mult is None:
        return None
    return max(1, int(num * mult))


def _first_category(categories: str) -> str:
    for category in categories.split(";"):
        if category:
            return category
    return ""


def _entry_has_non_apt_source(entry: DesktopEntry) -> bool:
    return bool(entry.flatpak_id or entry.snap_name or entry.appimage_path or "/snap/" in entry.exec_command)


def _extract_appimage_path(exec_command: str) -> str:
    for token in _clean_exec_parts(exec_command):
        if ".appimage" in token.lower():
            before, _separator, _after = token.lower().partition(".appimage")
            end = len(before) + len(".appimage")
            return _normalize_path(token[:end])
    return ""


def _clean_exec_command(exec_command: str) -> str:
    return " ".join(shlex.quote(part) for part in _clean_exec_parts(exec_command))


def _clean_exec_parts(exec_command: str) -> list[str]:
    if not exec_command:
        return []
    try:
        parts = shlex.split(exec_command)
    except ValueError:
        parts = exec_command.split()

    cleaned = [part for part in parts if not re.fullmatch(r"%[fFuUdDnNickvm]", part)]
    if cleaned and cleaned[0] == "env":
        cleaned = cleaned[1:]
        while cleaned and "=" in cleaned[0] and not cleaned[0].startswith("/"):
            cleaned = cleaned[1:]
    return cleaned


def _exec_first_token(exec_command: str) -> str:
    parts = _clean_exec_parts(exec_command)
    return parts[0] if parts else ""


def _snap_name_from_desktop(entry: DesktopEntry) -> str:
    command = _exec_first_token(entry.exec_command)
    if "/snap/bin/" in command:
        return Path(command).name.split(".", 1)[0]
    name = Path(entry.path).name
    if "_" in name:
        return name.split("_", 1)[0]
    return ""


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _name_from_appimage(path: str) -> str:
    name = Path(path).stem
    name = re.sub(r"[-_.]?(x86_64|amd64|aarch64|arm64)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[-_.]?\d+(\.\d+){1,3}.*$", "", name)
    name = name.replace("_", " ").replace("-", " ").strip()
    return name or Path(path).stem


def _appimage_version(entry: DesktopEntry | None, path: str) -> str:
    if entry and entry.appimage_update_info:
        return ""
    match = re.search(r"(\d+\.\d+(?:\.\d+)*)", Path(path).stem)
    return match.group(1) if match else ""


def _flatpak_desktop_dirs() -> list[str]:
    return [
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    ]


def _flatpak_desktop_path(app_id: str, installation: str) -> str:
    if installation == "user":
        return os.path.expanduser(f"~/.local/share/flatpak/exports/share/applications/{app_id}.desktop")
    return f"/var/lib/flatpak/exports/share/applications/{app_id}.desktop"


def _flatpak_install_path(app_id: str, installation: str) -> str:
    if installation == "user":
        return os.path.expanduser(f"~/.local/share/flatpak/app/{app_id}")
    return f"/var/lib/flatpak/app/{app_id}"


def _flatpak_last_updated(install_path: str) -> str:
    """Return YYYY-MM-DD of the last update by checking the 'active' deploy symlink mtime."""
    # Structure: {install_path}/{arch}/{branch}/active  (symlink recreated on update)
    matches = glob.glob(os.path.join(install_path, "*", "*", "active"))
    if not matches:
        return ""
    try:
        ts = max(os.lstat(p).st_mtime for p in matches)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except OSError:
        return ""


def _dedupe_applications(
    applications: list[UnifiedApplication],
    _seen_desktop_files: set[str] | None = None,
) -> list[UnifiedApplication]:
    by_id: dict[str, UnifiedApplication] = {}
    for application in applications:
        by_id[application.id] = application
    return list(by_id.values())
