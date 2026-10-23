#!/usr/bin/env python3
"""Translation integrity: parity, coverage, placeholders and duplicate keys.

The interface must never fall back to a raw key or a half-translated string.
These tests fail if a new ``t(lang, "key")`` call has no entry, if a Turkish and
English entry disagree on their format placeholders, or if a translation table
silently defines the same key twice (the later value wins at runtime).
"""

import ast
from pathlib import Path
import re
import unittest

from sourcedock.i18n import SUPPORTED_LANGUAGES, TRANSLATIONS, detect_system_language

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "sourcedock"
I18N_FILE = PACKAGE / "i18n.py"

STATIC_KEY_PATTERN = re.compile(r"""\bt\(\s*[^,()]+,\s*"([A-Za-z0-9_]+)"\s*[,)]""")
FSTRING_KEY_PATTERN = re.compile(r"""\bt\(\s*[^,()]+,\s*f"([A-Za-z0-9_]*)\{""")


def _iter_source_files():
    for path in PACKAGE.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        yield path


class TestTranslationTables(unittest.TestCase):
    def test_turkish_and_english_share_the_same_keys(self):
        tr, en = set(TRANSLATIONS["tr"]), set(TRANSLATIONS["en"])
        self.assertEqual(tr - en, set(), "keys missing from English")
        self.assertEqual(en - tr, set(), "keys missing from Turkish")

    def test_every_key_has_a_non_empty_value_in_both_languages(self):
        for language in SUPPORTED_LANGUAGES:
            for key, value in TRANSLATIONS[language].items():
                with self.subTest(language=language, key=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip(), f"{language}:{key} is empty")

    def test_format_placeholders_match_across_languages(self):
        for language, values in TRANSLATIONS.items():
            for key, value in values.items():
                en_value = TRANSLATIONS["en"].get(key, "")
                with self.subTest(language=language, key=key):
                    self.assertEqual(
                        set(re.findall(r"{(\w+)", value)),
                        set(re.findall(r"{(\w+)", en_value)),
                        f"placeholder mismatch for {language}:{key}",
                    )

    def test_all_supported_locales_are_loaded(self):
        self.assertEqual(set(SUPPORTED_LANGUAGES), set(TRANSLATIONS))
        self.assertGreaterEqual(len(SUPPORTED_LANGUAGES), 6)

    def test_system_locale_mapping(self):
        cases = {
            "tr_TR.UTF-8": "tr", "en_GB.UTF-8": "en", "de_AT.UTF-8": "de",
            "es_MX.UTF-8": "es", "pt_BR.UTF-8": "pt_BR", "fr_CA.UTF-8": "fr",
            "pt_PT.UTF-8": "en",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    detect_system_language({"LANG": value}), expected
                )

    def test_translation_tables_have_no_duplicate_keys(self):
        tree = ast.parse(I18N_FILE.read_text(encoding="utf-8"))
        duplicates = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            seen = set()
            for key in node.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if key.value in seen:
                    duplicates.append((key.value, key.lineno))
                seen.add(key.value)
        self.assertEqual(duplicates, [], f"duplicate translation keys: {duplicates}")


class TestTranslationCoverage(unittest.TestCase):
    def test_every_static_lookup_resolves_to_a_translation(self):
        known = set(TRANSLATIONS["tr"])
        missing = []
        for path in _iter_source_files():
            text = path.read_text(encoding="utf-8")
            for key in STATIC_KEY_PATTERN.findall(text):
                if key not in known:
                    missing.append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(missing, [], f"untranslated lookup keys: {sorted(set(missing))}")

    def test_every_dynamic_key_family_has_entries(self):
        known = set(TRANSLATIONS["tr"])
        missing_prefixes = []
        for path in _iter_source_files():
            text = path.read_text(encoding="utf-8")
            for prefix in FSTRING_KEY_PATTERN.findall(text):
                if not prefix:
                    continue
                if not any(key.startswith(prefix) for key in known):
                    missing_prefixes.append(f"{path.relative_to(ROOT)}:{prefix}")
        self.assertEqual(
            missing_prefixes, [], f"dynamic key families without translations: {sorted(set(missing_prefixes))}"
        )


class TestTranslationCatalogExport(unittest.TestCase):
    def test_pot_template_covers_every_key(self):
        from tools.translation_catalog import render_pot

        pot = render_pot()
        for key in TRANSLATIONS["en"]:
            with self.subTest(key=key):
                self.assertIn(f'msgid "{key}"', pot)

    def test_csv_export_has_a_row_per_key_and_language(self):
        from tools.translation_catalog import render_csv

        rows = [line for line in render_csv().splitlines() if line]
        self.assertEqual(rows[0], "key,language,text")
        self.assertEqual(len(rows) - 1, len(TRANSLATIONS) * len(TRANSLATIONS["en"]))

    def test_catalog_check_reports_no_problems(self):
        from tools.translation_catalog import check

        self.assertEqual(check(), [])


if __name__ == "__main__":
    unittest.main()
