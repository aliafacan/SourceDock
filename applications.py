#!/usr/bin/env python3
"""Geriye dönük uyumluluk için applications re-export."""

from sourcedock.core.models import (
    DESKTOP_DIRS,
    PACKAGE_MANAGER_SOURCES,
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_PORTABLE,
    SOURCE_SNAP,
    ApplicationIssue,
    ApplicationSnapshot,
    DesktopEntry,
    LocalPackageInfo,
    PackageInfo,
    UnifiedApplication,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.scanner import DesktopEntryScanner
from sourcedock.backend.apt import AptProvider
from sourcedock.backend.flatpak import FlatpakProvider
from sourcedock.backend.snap import SnapProvider
from sourcedock.backend.appimage import AppImageProvider
from sourcedock.backend.portable import PortableProvider
from sourcedock.backend.manager import ApplicationRegistry

__all__ = [
    "DESKTOP_DIRS",
    "PACKAGE_MANAGER_SOURCES",
    "SOURCE_APPIMAGE",
    "SOURCE_APT",
    "SOURCE_FLATPAK",
    "SOURCE_PORTABLE",
    "SOURCE_SNAP",
    "ApplicationIssue",
    "ApplicationRegistry",
    "ApplicationSnapshot",
    "DesktopEntry",
    "LocalPackageInfo",
    "PackageInfo",
    "UnifiedApplication",
    "CommandRunner",
    "DesktopEntryScanner",
    "AptProvider",
    "FlatpakProvider",
    "SnapProvider",
    "AppImageProvider",
    "PortableProvider",
]
