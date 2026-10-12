#!/usr/bin/env python3
"""Kullanıcı tercihleri yükleme ve kaydetme."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import locale
import os


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "zorin-app-manager")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")
SUPPORTED_LANGUAGES = {"tr", "en"}
SUPPORTED_THEMES = {"dark", "light"}


@dataclass
class AppPreferences:
    language: str
    theme: str


class PreferencesStore:
    def load(self) -> AppPreferences:
        defaults = AppPreferences(language=self._default_language(), theme="dark")
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, TypeError):
            return defaults

        language = raw.get("language", defaults.language)
        theme = raw.get("theme", defaults.theme)
        if language not in SUPPORTED_LANGUAGES:
            language = defaults.language
        if theme not in SUPPORTED_THEMES:
            theme = defaults.theme
        return AppPreferences(language=language, theme=theme)

    def save(self, preferences: AppPreferences) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(asdict(preferences), handle, ensure_ascii=False, indent=2)

    def _default_language(self) -> str:
        system_locale, _ = locale.getlocale()
        if system_locale and system_locale.lower().startswith("tr"):
            return "tr"
        return "en"
