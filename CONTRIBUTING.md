# Contributing to SourceDock

Thank you for helping improve SourceDock. This guide describes the project’s
development expectations and the checks required before opening a pull request.
For community expectations, see the [Code of Conduct](CODE_OF_CONDUCT.md). For
security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.

## Before you start

1. Search existing issues and pull requests before starting work.
2. For a substantial feature or behavior change, open an issue first so the scope
   and design can be discussed.
3. Keep changes focused. Avoid mixing unrelated refactors, formatting changes, or
   generated screenshots into a feature or bug-fix pull request.

## Development environment

SourceDock is a Python 3.10+ GTK 3 application. On Debian, Ubuntu, or Zorin OS,
install the runtime and test dependencies with:

```bash
sudo apt update
sudo apt install python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 \
  xvfb openbox x11-utils dpkg-dev desktop-file-utils appstream
```

Run the application from the repository root:

```bash
python3 main.py
python3 main.py /path/to/package.deb  # standalone package preview
```

The version is defined in `sourcedock/constants.py`. The `sourcedock/` package is
the implementation source of truth; the root-level compatibility modules should
not receive new architecture unless a change explicitly requires it.

## Code and architecture

- Keep UI code in `sourcedock/ui/`, domain and process logic in `sourcedock/core/`,
  provider integrations in `sourcedock/backend/`, and store/catalog logic in
  `sourcedock/store/`.
- Prefer small, cohesive modules over growing monolithic files.
- Keep privileged operations explicit and constrained. Do not add code that runs
  the GUI as root, bypasses authorization, executes untrusted local files, or logs
  credentials and private paths.
- Preserve the project’s provider status model: APT is the primary native
  integration; other providers may be optional or experimental.
- Use clear names and comments for security-sensitive behavior. Do not silently
  weaken an existing warning or validation rule.

## Localization

Every user-visible string must use the existing translation system. Add new keys to
all six catalogues under `sourcedock/locales/` (`en`, `tr`, `de`, `es`, `pt_BR`,
`fr`), keep placeholders and markup identical, and include the text in the relevant
refresh path when runtime language switching applies.

Run the localization checks after changing catalogues:

```bash
python3 tools/translation_catalog.py --check
python3 -m unittest tests.test_i18n_integrity
```

See [docs/LOCALIZATION.md](docs/LOCALIZATION.md) for the translation workflow.

## Required checks

Run the same checks used by CI before submitting a pull request:

```bash
python3 -m venv /tmp/sourcedock-lint
/tmp/sourcedock-lint/bin/pip install -r requirements-dev.txt
/tmp/sourcedock-lint/bin/ruff check .
/usr/bin/python3 -m compileall -q main.py sourcedock tests tools
bash packaging/build_deb.sh dist
```

Run the guarded test suite with a display server and window manager:

```bash
xvfb-run -a bash -c 'openbox >/tmp/sourcedock-test-wm.log 2>&1 & wm=$!; trap "kill $wm 2>/dev/null || true" EXIT; /usr/bin/python3 tools/run_tests.py --require-wm'
```

See [tests/README.md](tests/README.md) for test layers, supported skips, and
environment-specific requirements. Tests must not install, remove, or update
packages on the host system.

## Documentation and screenshots

Update affected documentation when behavior, compatibility, security boundaries,
or user-facing workflows change. Screenshots must come from the real GTK smoke
harness; do not use HTML mockups or fabricated progress, versions, or results.
Remove personal paths and other private data before committing an image.

## Pull requests

1. Fork the repository and create a focused branch, for example:
   `git switch -c fix/describe-the-change`.
2. Implement the change with tests or documentation updates as appropriate.
3. Use a clear Conventional Commit-style subject, such as `fix: handle stale
   package metadata` or `docs: clarify release verification`.
4. Run the required checks and include relevant results in the pull request.
5. Explain the user impact, compatibility implications, security considerations,
   and any known limitations. Keep screenshots and logs free of secrets.

Maintainers may request changes, squash commits, or adjust the final commit
message before merging. A pull request must satisfy the Code of Conduct and the
project’s security and quality requirements.

## Questions

For general questions, use a GitHub issue or discussion when available. Do not
publish a security vulnerability; report it privately according to [SECURITY.md](SECURITY.md).

---

# SourceDock’e katkıda bulunma

SourceDock’i geliştirmeye yardımcı olduğunuz için teşekkür ederiz. Geliştirme
kuralları ve pull request öncesi kontroller için bu belgeyi izleyin. Topluluk
beklentileri için [Davranış Kuralları](CODE_OF_CONDUCT.md), güvenlik açıkları için
ise [SECURITY.md](SECURITY.md) belgesini kullanın; güvenlik açığını herkese açık
issue olarak paylaşmayın.

## Kısa kurallar

- Mevcut issue ve pull request’leri kontrol edin; büyük değişiklikleri başlamadan
  önce issue üzerinden tartışın.
- Değişiklikleri odaklı tutun; ilgisiz refactor, biçim değişikliği veya ekran
  görüntülerini aynı pull request’e eklemeyin.
- Kullanıcıya görünen her metni çeviri sistemi üzerinden ekleyin ve altı katalogda
  (`en`, `tr`, `de`, `es`, `pt_BR`, `fr`) güncelleyin.
- Yetkili işlemleri, kimlik bilgilerini ve yerel dosya güvenliğini zayıflatmayın.
- Değişiklikle ilgili testleri çalıştırın; sonuçları pull request açıklamasında belirtin.

Geliştirme ortamı, mimari sınırlar, yerelleştirme, test, paketleme ve pull request
ayrıntıları için bu belgenin İngilizce bölümü ve [docs/LOCALIZATION.md](docs/LOCALIZATION.md)
referans alınmalıdır.
