#!/usr/bin/env python3
"""Flatpak paket yöneticisi sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import glob
import os
from pathlib import Path

from voltapp.core.models import (
    SOURCE_FLATPAK,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import (
    DesktopEntryScanner,
    _first_category,
)


def _parse_human_size_kib(size_str: str) -> int | None:
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


def _flatpak_dates(install_path: str) -> tuple[str, str]:
    if not os.path.exists(install_path):
        return "", ""
    installed_date = ""
    last_updated = ""
    try:
        st = os.stat(install_path)
        installed_date = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d")
    except OSError:
        pass
    matches = glob.glob(os.path.join(install_path, "*", "*", "active"))
    if matches:
        try:
            ts = max(os.lstat(p).st_mtime for p in matches)
            last_updated = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except OSError:
            pass
    if not last_updated:
        last_updated = installed_date
    if not installed_date:
        installed_date = last_updated
    return installed_date, last_updated


class FlatpakProvider:
    """Sistemdeki Flatpak paketlerini yöneten ve listeleyen sağlayıcı."""

    source = SOURCE_FLATPAK

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner

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
            installed_date, last_updated = _flatpak_dates(install_path)
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
                    installed_date=installed_date,
                    last_updated=last_updated,
                )
            )
        return applications

    def _update_ids(self) -> set[str]:
        try:
            result = self.runner.run(
                ["flatpak", "remote-ls", "--updates", "--app", "--columns=application"],
                timeout=8,
                check=False,
            )
            if result.returncode != 0:
                return set()
            return {line.strip() for line in result.stdout.splitlines() if line.strip()}
        except Exception:
            return set()


