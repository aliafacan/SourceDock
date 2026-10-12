#!/usr/bin/env python3
"""VoltApp temel veri modelleri ve sabitleri."""

from __future__ import annotations

from dataclasses import dataclass, field
import os

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
    """Yüklü bir uygulamanın standartlaştırılmış temsili."""
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
    """Uygulama veya paketle ilgili tanılama uyarısı."""
    kind: str
    title: str
    detail: str = ""
    path: str = ""


@dataclass
class PackageInfo:
    """Ham paket yöneticisi paket bilgisi."""
    name: str
    version: str
    installed_size_kib: int | None
    description: str
    update_available: bool
    new_version: str = ""


@dataclass(frozen=True)
class ApplicationSnapshot:
    """Tüm yüklü uygulamaların ve tanılama bilgilerinin anlık görüntüsü."""
    applications: list[UnifiedApplication]
    issues: list[ApplicationIssue] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DesktopEntry:
    """.desktop dosyasından çözümlenen uygulama bilgisi."""
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


@dataclass(frozen=True)
class StoreResult:
    """Mağazadan dönen uygulama arama sonucu."""
    name: str
    app_id: str
    description: str
    source: str
    version: str
    remote: str
    download_size_str: str = ""
    icon_path: str = ""

