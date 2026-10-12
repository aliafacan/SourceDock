#!/usr/bin/env python3
"""Snap paket yöneticisi sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from voltapp.core.models import (
    SOURCE_SNAP,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import (
    DesktopEntryScanner,
    _first_category,
    _snap_name_from_desktop,
)


def _dedupe_applications(applications: list[UnifiedApplication]) -> list[UnifiedApplication]:
    by_id: dict[str, UnifiedApplication] = {}
    for app in applications:
        by_id[app.id] = app
    return list(by_id.values())


class SnapProvider:
    """Sistemdeki Snap paketlerini yöneten ve listeleyen sağlayıcı."""

    source = SOURCE_SNAP

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.runner.command_exists("snap"):
            return []

        snaps = self._snap_metadata()
        if not snaps:
            return []

        update_names = self._update_names()
        applications: list[UnifiedApplication] = []
        for entry in self.scanner.list_entries(["/var/lib/snapd/desktop/applications", os.path.expanduser("~/.local/share/applications")]):
            if not entry.visible:
                continue
            snap_name = entry.snap_name or _snap_name_from_desktop(entry)
            if not snap_name or snap_name not in snaps:
                continue
            version = snaps[snap_name]
            size_kib, installed_date, last_updated = self._get_snap_size_and_dates(snap_name)
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
                    installed_size_kib=size_kib,
                    installed_date=installed_date,
                    last_updated=last_updated,
                )
            )

        return _dedupe_applications(applications)

    def _get_snap_size_and_dates(self, snap_name: str) -> tuple[int | None, str, str]:
        size_kib: int | None = None
        installed_date = ""
        last_updated = ""

        # /var/snap/<snap_name> dizini ilk kurulum hakkında güçlü ipucu verir
        var_snap_dir = f"/var/snap/{snap_name}"
        if os.path.exists(var_snap_dir):
            try:
                st = os.stat(var_snap_dir)
                installed_date = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d")
            except OSError:
                pass

        current_dir = f"/snap/{snap_name}/current"
        if os.path.exists(current_dir):
            try:
                mtime = os.path.getmtime(current_dir)
                last_updated = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            except OSError:
                pass

        snaps_dir = "/var/lib/snapd/snaps"
        if os.path.exists(snaps_dir):
            try:
                prefix = f"{snap_name}_"
                candidates = [
                    os.path.join(snaps_dir, f)
                    for f in os.listdir(snaps_dir)
                    if f.startswith(prefix) and f.endswith(".snap")
                ]
                if candidates:
                    latest = max(candidates, key=os.path.getmtime)
                    oldest = min(candidates, key=os.path.getmtime)
                    size_kib = os.path.getsize(latest) // 1024
                    oldest_date = datetime.fromtimestamp(os.path.getmtime(oldest)).strftime("%Y-%m-%d")
                    latest_date = datetime.fromtimestamp(os.path.getmtime(latest)).strftime("%Y-%m-%d")

                    if not installed_date or oldest_date < installed_date:
                        installed_date = oldest_date
                    if not last_updated:
                        last_updated = latest_date
            except Exception:
                pass

        if not last_updated:
            last_updated = installed_date
        if not installed_date:
            installed_date = last_updated

        return size_kib, installed_date, last_updated

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

