#!/usr/bin/env python3
"""Geriye dönük uyumluluk için sourcedock.i18n modülünü dışa aktarır."""

from sourcedock.i18n import (
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    detect_system_language,
    discover_languages,
    load_locale,
    t,
    translate_backend_message,
)

__all__ = [
    "SUPPORTED_LANGUAGES", "TRANSLATIONS", "detect_system_language",
    "discover_languages", "load_locale", "t", "translate_backend_message",
]
