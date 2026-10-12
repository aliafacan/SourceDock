#!/usr/bin/env python3
"""Geriye dönük uyumluluk için applications re-export."""

from voltapp.core.models import (
    DESKTOP_DIRS,
    PACKAGE_MANAGER_SOURCES,
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    ApplicationIssue,
    ApplicationSnapshot,
    DesktopEntry,
    PackageInfo,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import DesktopEntryScanner
from voltapp.backend.apt import AptProvider
from voltapp.backend.flatpak import FlatpakProvider
from voltapp.backend.snap import SnapProvider
from voltapp.backend.appimage import AppImageProvider
from voltapp.backend.manager import ApplicationRegistry

__all__ = [
    "DESKTOP_DIRS",
    "PACKAGE_MANAGER_SOURCES",
    "SOURCE_APPIMAGE",
    "SOURCE_APT",
    "SOURCE_FLATPAK",
    "SOURCE_SNAP",
    "ApplicationIssue",
    "ApplicationRegistry",
    "ApplicationSnapshot",
    "DesktopEntry",
    "PackageInfo",
    "UnifiedApplication",
    "CommandRunner",
    "DesktopEntryScanner",
    "AptProvider",
    "FlatpakProvider",
    "SnapProvider",
    "AppImageProvider",
]
