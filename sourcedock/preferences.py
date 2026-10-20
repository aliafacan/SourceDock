#!/usr/bin/env python3
"""Kullanıcı tercihleri yükleme ve kaydetme."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import locale
import os
from pathlib import Path
from sourcedock.core.json_store import write_json


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "sourcedock")
LEGACY_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "voltapp")
OLDER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "zorin-app-manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_CONFIG_PATH = os.path.join(LEGACY_CONFIG_DIR, "settings.json")
OLDER_CONFIG_PATH = os.path.join(OLDER_CONFIG_DIR, "settings.json")
SUPPORTED_LANGUAGES = {"tr", "en"}
SUPPORTED_THEMES = {"system", "dark", "light"}
SUPPORTED_SCALES = {"90", "100", "110", "125"}


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
        return AppPreferences(
            language=language,
            theme=theme,
            scale=scale,
            preferred_source=preferred_source,
            check_updates_on_start=raw.get("check_updates_on_start") is True,
            notifications_enabled=raw.get("notifications_enabled", True) is not False,
            detailed_table_default=raw.get("detailed_table_default", True) is not False,
            show_technical_packages=raw.get("show_technical_packages") is True,
        )


    def save(self, preferences: AppPreferences) -> None:
        write_json(Path(CONFIG_PATH), asdict(preferences))

    def _default_language(self) -> str:
        system_locale, _ = locale.getlocale()
        if system_locale and system_locale.lower().startswith("tr"):
            return "tr"
        return "en"
