#!/usr/bin/env python3
"""AppImage taşınabilir uygulamalar sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from voltapp.core.models import (
    SOURCE_APPIMAGE,
    DesktopEntry,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import (
    DesktopEntryScanner,
    _appimage_version,
    _first_category,
    _name_from_appimage,
    _normalize_path,
)


class AppImageProvider:
    """Sistemdeki bağımsız .AppImage dosyalarını yöneten sağlayıcı."""

    source = SOURCE_APPIMAGE

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner

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

