#!/usr/bin/env python3
""".desktop dosyaları ve menü girdileri tarayıcısı."""

from __future__ import annotations

from configparser import ConfigParser
import locale
import os
from pathlib import Path
import re
import shlex

from voltapp.core.errors import BackendError
from voltapp.core.models import DESKTOP_DIRS, DesktopEntry
from voltapp.core.runner import CommandRunner


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


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


class DesktopEntryScanner:
    """.desktop dosyalarını okuyan ve yapılandıran tarayıcı."""

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

