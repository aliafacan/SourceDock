#!/usr/bin/env python3
"""Kullanıcı tercihleri yükleme ve kaydetme."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from sourcedock.core.json_store import write_json
from sourcedock.i18n import SUPPORTED_LANGUAGES, detect_system_language


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "sourcedock")
LEGACY_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "voltapp")
OLDER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "zorin-app-manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_CONFIG_PATH = os.path.join(LEGACY_CONFIG_DIR, "settings.json")
OLDER_CONFIG_PATH = os.path.join(OLDER_CONFIG_DIR, "settings.json")
SUPPORTED_THEMES = {"system", "dark", "light"}
SUPPORTED_SCALES = {"90", "100", "110", "125"}
SUPPORTED_UPDATE_SCHEDULES = {"never", "on_start", "hourly", "daily", "weekly"}


@dataclass
class AppPreferences:
    language: str
    theme: str
    scale: str = "100"
    preferred_source: str = "all"
    check_updates_on_start: bool = False
    notifications_enabled: bool = True
    detailed_table_default: bool = True
    show_technical_packages: bool = False
    show_operation_details_by_default: bool = False
    update_schedule_native: str = "never"
    update_schedule_flatpak: str = "never"
    update_schedule_snap: str = "never"
    last_update_check_native: float = 0.0
    last_update_check_flatpak: float = 0.0
    last_update_check_snap: float = 0.0


class PreferencesStore:
    def load(self) -> AppPreferences:
        defaults = AppPreferences(language=self._default_language(), theme="system", scale="100")
        raw = None
        for target_path in (CONFIG_PATH, LEGACY_CONFIG_PATH, OLDER_CONFIG_PATH):
            if not os.path.exists(target_path):
                continue
            try:
                with open(target_path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                break
            except (OSError, ValueError, TypeError):
                continue
        if not isinstance(raw, dict):
            return defaults

        language = raw.get("language", defaults.language)
        theme = raw.get("theme", defaults.theme)
        scale = str(raw.get("scale", defaults.scale))
        if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
            language = defaults.language
        if not isinstance(theme, str) or theme not in SUPPORTED_THEMES:
            theme = defaults.theme
        if scale not in SUPPORTED_SCALES:
            scale = defaults.scale
        preferred_source = raw.get("preferred_source", "all")
        if not isinstance(preferred_source, str) or preferred_source not in {
            "all",
            "apt",
            "dnf",
            "pacman",
            "zypper",
            "flatpak",
            "snap",
        }:
            preferred_source = "all"
        check_on_start = raw.get("check_updates_on_start") is True
        default_schedule = "on_start" if check_on_start else "never"

        def _parse_schedule(key: str) -> str:
            val = raw.get(key, default_schedule)
            return val if isinstance(val, str) and val in SUPPORTED_UPDATE_SCHEDULES else default_schedule

        def _parse_ts(key: str) -> float:
            val = raw.get(key, 0.0)
            try:
                return max(0.0, float(val))
            except (TypeError, ValueError):
                return 0.0

        return AppPreferences(
            language=language,
            theme=theme,
            scale=scale,
            preferred_source=preferred_source,
            check_updates_on_start=check_on_start,
            notifications_enabled=raw.get("notifications_enabled", True) is not False,
            detailed_table_default=raw.get("detailed_table_default", True) is not False,
            show_technical_packages=raw.get("show_technical_packages") is True,
            show_operation_details_by_default=raw.get("show_operation_details_by_default") is True,
            update_schedule_native=_parse_schedule("update_schedule_native"),
            update_schedule_flatpak=_parse_schedule("update_schedule_flatpak"),
            update_schedule_snap=_parse_schedule("update_schedule_snap"),
            last_update_check_native=_parse_ts("last_update_check_native"),
            last_update_check_flatpak=_parse_ts("last_update_check_flatpak"),
            last_update_check_snap=_parse_ts("last_update_check_snap"),
        )


    def save(self, preferences: AppPreferences) -> None:
        write_json(Path(CONFIG_PATH), asdict(preferences))

    def _default_language(self) -> str:
        return detect_system_language()
