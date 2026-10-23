#!/usr/bin/env python3
"""Runtime localisation for SourceDock, backed by UTF-8 JSON catalogues."""

from __future__ import annotations

import json
import locale
import logging
import os
from functools import lru_cache
from pathlib import Path
import re

LOGGER = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).resolve().parent
LOCALES_DIR = PACKAGE_DIR / "locales"
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch", "es": "Español",
    "pt_BR": "Português (Brasil)", "fr": "Français",
}
_LOCALE_FILE = re.compile(r"^[A-Za-z]{2,3}(?:_[A-Za-z]{2,4})?\.json$")
_PLACEHOLDER = re.compile(r"{([A-Za-z_]\w*)}")


def _locale_dir() -> Path:
    override = os.environ.get("SOURCEDOCK_LOCALES_DIR")
    return Path(override).expanduser() if override else LOCALES_DIR


def discover_languages() -> dict[str, str]:
    """Discover valid locale files in stable, canonical language order."""
    found = {}
    try:
        paths = sorted(_locale_dir().glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        if not _LOCALE_FILE.match(path.name):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            LOGGER.warning("Ignoring invalid locale file: %s", path)
            continue
        if isinstance(value, dict):
            found[path.stem] = LANGUAGE_NAMES.get(path.stem, path.stem)
    ordered = {code: found[code] for code in LANGUAGE_NAMES if code in found}
    for code in sorted(set(found) - set(ordered)):
        ordered[code] = found[code]
    return ordered


SUPPORTED_LANGUAGES = discover_languages()


@lru_cache(maxsize=None)
def load_locale(language: str) -> dict[str, str]:
    """Read a locale once and retain only string key/value pairs."""
    try:
        raw = json.loads((_locale_dir() / f"{language}.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        LOGGER.error("Unable to load locale %s: %s", language, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


TRANSLATIONS = {code: load_locale(code) for code in SUPPORTED_LANGUAGES}


def reload_locales() -> None:
    global SUPPORTED_LANGUAGES, TRANSLATIONS
    load_locale.cache_clear()
    SUPPORTED_LANGUAGES = discover_languages()
    TRANSLATIONS = {code: load_locale(code) for code in SUPPORTED_LANGUAGES}


def missing_keys(language: str) -> set[str]:
    return set(TRANSLATIONS.get(DEFAULT_LANGUAGE, {})) - set(TRANSLATIONS.get(language, {}))


def t(language: str, key: str, **kwargs) -> str:
    """Translate with English fallback and a visible, non-raw missing marker."""
    selected = language if language in TRANSLATIONS else DEFAULT_LANGUAGE
    text = TRANSLATIONS.get(selected, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(key)
        if text is None:
            LOGGER.warning("Missing translation: %s:%s", selected, key)
            text = f"[{key}]"
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            LOGGER.warning("Invalid format arguments for translation %s:%s", selected, key)
    return text


def detect_system_language(environ: dict[str, str] | None = None) -> str:
    """Resolve LANGUAGE, LC_ALL, LC_MESSAGES, LANG and Python locale safely."""
    env = os.environ if environ is None else environ
    candidates = []
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        candidates.extend(part.strip() for part in env.get(variable, "").split(":") if part.strip())
    try:
        detected, _ = locale.getlocale(locale.LC_MESSAGES)
        if detected:
            candidates.append(detected)
    except (locale.Error, ValueError):
        pass
    codes = {code.casefold(): code for code in SUPPORTED_LANGUAGES}
    for candidate in candidates:
        normalized = candidate.split("@", 1)[0].split(".", 1)[0].replace("-", "_")
        base, _, territory = normalized.partition("_")
        if base.casefold() == "pt" and territory.upper() == "BR" and "pt_BR" in SUPPORTED_LANGUAGES:
            return "pt_BR"
        if base.casefold() in codes:
            return codes[base.casefold()]
    return DEFAULT_LANGUAGE


def source_name(language: str, source: str) -> str:
    key = f"store_source_{source}"
    value = t(language, key)
    return source.upper() if value == f"[{key}]" else value


def translate_backend_message(language: str, message: str) -> str:
    if "Komut basarisiz oldu:" in message or "Komut başarısız oldu:" in message:
        suffix = message.split(":", 1)[1].strip() if ":" in message else ""
        return f"{t(language, 'error_command')} {suffix}".strip()
    return message


def translate_provider_error(language: str, message: str) -> str:
    source, _, detail = message.partition(":")
    if "timeout" in detail.casefold() or detail.strip().casefold() == "timeout":
        return t(language, "provider_timeout", source=source_name(language, source.strip().lower()))
    return message


def translate_provider_notice(language: str, message: str, *, compact: bool = False) -> str:
    match = re.fullmatch(r"(?P<source>\w+) \(sistem\): (?P<count>\d+) arayüzsüz paket güncellenebilir → (?P<packages>.*)", message)
    if not match:
        return message
    summary = t(language, "updates_status_system_packages", source=source_name(language, match.group("source")), count=int(match.group("count")))
    return summary if compact else f"{summary}: {match.group('packages')}"


def format_placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))
