# Localization And Translation Contributions

SourceDock ships Turkish, English, German, Spanish, Brazilian Portuguese and
French at runtime. Each catalogue is an independently editable UTF-8 JSON file
under `sourcedock/locales/`. The compatibility mapping
`sourcedock.i18n.TRANSLATIONS` is loaded from those files and keeps old imports
working. The `t(language, key, **kwargs)` helper applies safe English fallback
and `str.format` placeholders without a runtime gettext dependency.

## Contract

- Every key MUST exist in all supported languages with a non-empty value.
- Placeholders (`{name}`, `{count}`, ...) MUST match the English reference.
- A key MUST NOT be defined twice in the same table (the later value silently
  wins today, which hides mistakes).
- UI code MUST resolve text through `t(...)`. Do not hardcode display strings.
  Backend/CLI diagnostics are reconciled through the `translate_*` helpers in
  `sourcedock/i18n.py`.

These rules are enforced by `tests/test_i18n_integrity.py`, which fails the build
if a lookup has no entry or a dynamic `f"prefix_{x}"` family is missing.

## Export for translators and Weblate

```bash
python3 tools/translation_catalog.py --export po
python3 tools/translation_catalog.py --check
```

`--export po` writes `sourcedock.pot` (a gettext template whose `msgid` is the
stable key and whose comments carry the current text for every language) and
`sourcedock.csv` (`key,language,text`) into the target directory. `--check`
validates parity and emptiness and exits non-zero on a problem.

The generated files are review inputs. Merge translated text back into the
appropriate JSON catalogue; the runtime stays dependency-free.

## Weblate / hosted flow (proposal)

1. Point the hosted tool at `sourcedock.pot` produced by `--export`.
2. Treat the symbolic key as the unit of translation (`msgctxt`-style). English is
   the reference language and is never merged from the hosted tool blindly.
3. Open a pull request that only edits the affected JSON catalogue for the
   language. The integrity test and the GTK smoke run must pass.

## Adding a new language (proposal)

Adding a language only requires adding a valid `<language>.json` file to
`sourcedock/locales/`; the runtime registry, settings selector and catalogue
tool discover it automatically. Add a display name to `LANGUAGE_NAMES` when the
code is not one of the standard six codes.
