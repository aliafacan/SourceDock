#!/usr/bin/env python3
"""AppImage taşınabilir uygulamalar sağlayıcısı."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

from sourcedock.core.models import (
    SOURCE_APPIMAGE,
    DesktopEntry,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.scanner import (
    DesktopEntryScanner,
    _appimage_version,
    _first_category,
    _name_from_appimage,
    _normalize_path,
)

# Update-information schemes understood by AppImageUpdate. A value is only
# treated as "update supported" when it declares one of these schemes with the
# required fields, so the interface never implies a safe update path that the
# metadata cannot actually drive.
SUPPORTED_UPDATE_SCHEMES = {
    "zsync": 2,
    "bzsync": 2,
    "bintray-zsync": 3,
    "gh-releases-zsync": 4,
}


def is_valid_update_information(value: str) -> bool:
    """Return True only for a well-formed, known AppImage update descriptor."""
    if not value or not isinstance(value, str):
        return False
    parts = [part.strip() for part in value.split("|")]
    scheme = parts[0].casefold()
    required = SUPPORTED_UPDATE_SCHEMES.get(scheme)
    if required is None or len(parts) < required:
        return False
    if any(not part for part in parts[:required]):
        return False
    if scheme in {"zsync", "bzsync"}:
        return parts[1].startswith(("http://", "https://"))
    return True



class AppImageProvider:
    """Sistemdeki bağımsız .AppImage dosyalarını yöneten sağlayıcı."""

    source = SOURCE_APPIMAGE

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner):
        self.runner = runner
        self.scanner = scanner

    def list_applications(self) -> list[UnifiedApplication]:
        appimage_update_available = self.runner.command_exists("AppImageUpdate")
        by_path: dict[str, UnifiedApplication] = {}

        for entry in self.scanner.list_entries(
            [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications"]
        ):
            if not entry.visible or not entry.appimage_path:
                continue
            path = _normalize_path(entry.appimage_path)
            by_path[path] = self._application_from_path(path, entry, appimage_update_available)

        for path in self._scan_appimage_files():
            normalized_path = _normalize_path(path)
            if normalized_path in by_path:
                continue
            by_path[normalized_path] = self._application_from_path(
                normalized_path, None, appimage_update_available
            )

        return sorted(by_path.values(), key=lambda app: app.name.lower())

    def _application_from_path(
        self,
        path: str,
        entry: DesktopEntry | None,
        appimage_update_available: bool,
    ) -> UnifiedApplication:
        name = entry.name if entry else _name_from_appimage(path)
        update_info = entry.appimage_update_info if entry else ""
        update_supported = bool(appimage_update_available and is_valid_update_information(update_info))
        size = None
        try:
            size = max(1, os.path.getsize(path) // 1024)
        except OSError:
            pass
        installed_date = ""
        last_updated = ""
        try:
            st = os.stat(path)
            # Linux'ta en erken zaman genellikle ilk indirilme / oluşturulmadır
            first_ts = min(st.st_ctime, st.st_mtime)
            latest_ts = max(st.st_ctime, st.st_mtime)
            installed_date = datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
            last_updated = datetime.fromtimestamp(latest_ts).strftime("%Y-%m-%d")
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
            installed_date=installed_date,
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
