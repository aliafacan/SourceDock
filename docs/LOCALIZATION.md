# Localization And Translation Contributions

SourceDock ships Turkish (TR) and English (EN) at runtime. Strings live in
`sourcedock/i18n.py` in two tables that the module merges at import time:

- `TRANSLATIONS["tr"]` / `TRANSLATIONS["en"]` for the historical keys.
- `_UI_STRINGS`, a `{key: (turkish, english)}` table for newer keys.

Keeping both tables in one module means the application has no runtime gettext
dependency: `sourcedock.i18n.t(language, key, **kwargs)` simply looks the text up
and applies `str.format` placeholders.

## Contract

- Every key MUST exist in both languages with a non-empty value.
- Placeholders (`{name}`, `{count}`, ...) MUST match between TR and EN.
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
stable key and whose comments carry the current EN/TR text) and
`sourcedock.csv` (`key,language,text`) into the target directory. `--check`
validates parity and emptiness and exits non-zero on a problem.

The generated files are review inputs. Merge translated text back into the
appropriate table in `sourcedock/i18n.py`; the runtime stays dependency-free.

## Weblate / hosted flow (proposal)

1. Point the hosted tool at `sourcedock.pot` produced by `--export`.
2. Treat the symbolic key as the unit of translation (`msgctxt`-style). English is
   the reference language and is never merged from the hosted tool blindly.
3. Open a pull request that only edits `sourcedock/i18n.py` for the affected
   language. The integrity test and the GTK smoke run must pass.

## Adding a new language (proposal)

The runtime currently resolves `tr` and falls back to `en`. Adding a third
language requires a new table plus locale detection and screenshot review; that
work is intentionally not folded into the current dictionaries.
