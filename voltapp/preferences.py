#!/usr/bin/env python3
"""Kullanıcı tercihleri yükleme ve kaydetme."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import locale
import os


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "voltapp")
LEGACY_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "zorin-app-manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_CONFIG_PATH = os.path.join(LEGACY_CONFIG_DIR, "settings.json")
SUPPORTED_LANGUAGES = {"tr", "en"}
SUPPORTED_THEMES = {"dark", "light"}
SUPPORTED_SCALES = {"90", "100", "110", "125"}


@dataclass
class AppPreferences:
    language: str
    theme: str
    scale: str = "100"


class PreferencesStore:
    def load(self) -> AppPreferences:
        defaults = AppPreferences(language=self._default_language(), theme="dark", scale="100")
        target_path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else LEGACY_CONFIG_PATH
        try:
            with open(target_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, TypeError):
            return defaults

        language = raw.get("language", defaults.language)
        theme = raw.get("theme", defaults.theme)
        scale = str(raw.get("scale", defaults.scale))
        if language not in SUPPORTED_LANGUAGES:
            language = defaults.language
        if theme not in SUPPORTED_THEMES:
            theme = defaults.theme
        if scale not in SUPPORTED_SCALES:
            scale = defaults.scale
        return AppPreferences(language=language, theme=theme, scale=scale)

    def save(self, preferences: AppPreferences) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(asdict(preferences), handle, ensure_ascii=False, indent=2)

    def _default_language(self) -> str:
        system_locale, _ = locale.getlocale()
        if system_locale and system_locale.lower().startswith("tr"):
            return "tr"
        return "en"
