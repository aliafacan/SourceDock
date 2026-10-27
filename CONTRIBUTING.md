<div align="center">

<a id="top"></a>
[🇬🇧 English](#english) &nbsp;•&nbsp; [🇹🇷 Türkçe](#turkish) &nbsp;•&nbsp; [🇩🇪 Deutsch](#german) &nbsp;•&nbsp; [🇪🇸 Español](#spanish) &nbsp;•&nbsp; [🇧🇷 Português (BR)](#portuguese) &nbsp;•&nbsp; [🇫🇷 Français](#french)

</div>

---

<a id="english"></a>
# 🇬🇧 Contributing to SourceDock

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

<a id="turkish"></a>
# 🇹🇷 SourceDock’e katkıda bulunma

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

[Başa dön](#top)

---

<a id="german"></a>
# 🇩🇪 Zu SourceDock beitragen

Vielen Dank für deine Hilfe bei SourceDock. Für Gemeinschaftsregeln siehe den
[Verhaltenskodex](CODE_OF_CONDUCT.md), für Sicherheitslücken die
[Sicherheitsrichtlinie](SECURITY.md). Sicherheitslücken dürfen nicht öffentlich gemeldet werden.

## Vor dem Start

- Suche zuerst nach bestehenden Issues und Pull Requests.
- Besprich größere Funktionen oder Verhaltensänderungen vorab in einem Issue.
- Halte Änderungen fokussiert und vermeide unabhängige Refactorings oder generierte Dateien.

## Entwicklung und Architektur

SourceDock ist eine Python-3.10+-GTK-3-Anwendung. Auf Debian, Ubuntu oder Zorin OS werden
Python/PyGObject, GTK 3, Xvfb, Openbox, `dpkg-dev`, `desktop-file-utils` und `appstream`
benötigt. Starte die Anwendung mit `python3 main.py`; ein lokales `.deb` kann mit
`python3 main.py /pfad/zum/paket.deb` geprüft werden.

UI-Code gehört nach `sourcedock/ui/`, Kern- und Prozesslogik nach `sourcedock/core/`,
Provider nach `sourcedock/backend/` und Kataloglogik nach `sourcedock/store/`. Die GUI darf
nicht als root laufen, Autorisierung darf nicht umgangen werden und Zugangsdaten oder private
Pfade dürfen nicht protokolliert werden. APT ist die primäre native Integration; andere
Provider können optional oder experimentell sein.

## Übersetzungen und Tests

Jeder sichtbare Text muss über das Übersetzungssystem laufen. Neue Schlüssel müssen in allen
sechs Katalogen unter `sourcedock/locales/` (`en`, `tr`, `de`, `es`, `pt_BR`, `fr`) vorhanden
sein. Platzhalter und Markup müssen übereinstimmen.

```bash
python3 tools/translation_catalog.py --check
python3 -m unittest tests.test_i18n_integrity
/tmp/sourcedock-lint/bin/ruff check .
/usr/bin/python3 -m compileall -q main.py sourcedock tests tools
bash packaging/build_deb.sh dist
xvfb-run -a bash -c 'openbox >/tmp/sourcedock-test-wm.log 2>&1 & wm=$!; trap "kill $wm 2>/dev/null || true" EXIT; /usr/bin/python3 tools/run_tests.py --require-wm'
```

Tests dürfen keine Pakete auf dem Host installieren, entfernen oder aktualisieren. Screenshots
müssen aus der echten GTK-Anwendung stammen und dürfen keine persönlichen Daten enthalten.

## Pull Requests

Erstelle einen fokussierten Branch, verwende eine klare Conventional-Commit-Betreffzeile,
führe die relevanten Prüfungen aus und beschreibe Benutzer-, Kompatibilitäts- und
Sicherheitsauswirkungen. Dokumentation muss bei Änderungen an Verhalten, Kompatibilität oder
Sicherheitsgrenzen aktualisiert werden.

[Zum Anfang](#top)

---

<a id="spanish"></a>
# 🇪🇸 Contribuir a SourceDock

Gracias por ayudar a mejorar SourceDock. Consulta el [código de conducta](CODE_OF_CONDUCT.md)
para las normas de la comunidad y [SECURITY.md](SECURITY.md) para vulnerabilidades; no
publiques una vulnerabilidad en un issue.

## Antes de empezar

- Busca issues y pull requests existentes.
- Discute las funciones importantes o cambios de comportamiento en un issue antes de comenzar.
- Mantén los cambios enfocados y evita refactors o archivos generados no relacionados.

## Desarrollo y arquitectura

SourceDock es una aplicación Python 3.10+ con GTK 3. Usa `python3 main.py` para ejecutarla y
`python3 main.py /ruta/al/paquete.deb` para previsualizar un paquete local. La interfaz debe
permanecer en `sourcedock/ui/`, la lógica central en `sourcedock/core/`, los proveedores en
`sourcedock/backend/` y los catálogos en `sourcedock/store/`. No ejecutes la GUI como root,
no evadas la autorización y no registres credenciales ni rutas privadas.

## Traducciones, pruebas y pull requests

Todo texto visible debe usar el sistema de traducción y existir en los seis catálogos
(`en`, `tr`, `de`, `es`, `pt_BR`, `fr`). Conserva los mismos marcadores y etiquetas. Ejecuta
`python3 tools/translation_catalog.py --check`, Ruff, `compileall`, la construcción del `.deb`
y la suite protegida con Xvfb/Openbox descrita en la sección inglesa. Las pruebas no deben
modificar la base de paquetes del sistema. Los pull requests deben explicar el impacto para
el usuario, la compatibilidad, la seguridad y las limitaciones conocidas.

[Volver al inicio](#top)

---

<a id="portuguese"></a>
# 🇧🇷 Contribuindo com o SourceDock

Obrigado por ajudar a melhorar o SourceDock. Consulte o [Código de Conduta](CODE_OF_CONDUCT.md)
para as regras da comunidade e [SECURITY.md](SECURITY.md) para vulnerabilidades; não publique
uma vulnerabilidade em uma issue.

## Antes de começar

- Pesquise issues e pull requests existentes.
- Discuta recursos importantes ou mudanças de comportamento em uma issue antes de começar.
- Mantenha as alterações focadas e evite refatorações ou arquivos gerados sem relação.

## Desenvolvimento e arquitetura

O SourceDock é uma aplicação Python 3.10+ com GTK 3. Execute `python3 main.py` e use
`python3 main.py /caminho/para/pacote.deb` para visualizar um pacote local. O código de UI
fica em `sourcedock/ui/`, a lógica central em `sourcedock/core/`, os provedores em
`sourcedock/backend/` e os catálogos em `sourcedock/store/`. A GUI não deve ser executada como
root, a autorização não deve ser contornada e credenciais ou caminhos privados não devem ser
registrados.

## Traduções, testes e pull requests

Todo texto visível deve usar o sistema de tradução e existir nos seis catálogos (`en`, `tr`,
`de`, `es`, `pt_BR`, `fr`), mantendo os mesmos placeholders e marcação. Execute as verificações
de catálogo, Ruff, `compileall`, build do `.deb` e a suíte protegida com Xvfb/Openbox descritas
na seção inglesa. Os testes não devem alterar o banco de pacotes do sistema. Pull requests
devem explicar impacto ao usuário, compatibilidade, segurança e limitações conhecidas.

[Voltar ao início](#top)

---

<a id="french"></a>
# 🇫🇷 Contribuer à SourceDock

Merci de contribuer à l’amélioration de SourceDock. Consultez le [code de conduite](CODE_OF_CONDUCT.md)
pour les règles de la communauté et [SECURITY.md](SECURITY.md) pour les vulnérabilités ; ne
publiez jamais une vulnérabilité dans une issue.

## Avant de commencer

- Recherchez les issues et pull requests existantes.
- Discutez les fonctionnalités importantes ou les changements de comportement dans une issue.
- Gardez les changements ciblés et évitez les refactorings ou fichiers générés sans rapport.

## Développement et architecture

SourceDock est une application Python 3.10+ basée sur GTK 3. Lancez-la avec `python3 main.py`
et prévisualisez un paquet local avec `python3 main.py /chemin/vers/paquet.deb`. Le code UI
reste dans `sourcedock/ui/`, la logique centrale dans `sourcedock/core/`, les fournisseurs dans
`sourcedock/backend/` et les catalogues dans `sourcedock/store/`. L’interface ne doit pas être
exécutée en root ; l’autorisation ne doit pas être contournée et les identifiants ou chemins
privés ne doivent pas être journalisés.

## Traductions, tests et pull requests

Tout texte visible doit utiliser le système de traduction et exister dans les six catalogues
(`en`, `tr`, `de`, `es`, `pt_BR`, `fr`), avec les mêmes placeholders et balises. Exécutez les
vérifications des catalogues, Ruff, `compileall`, la construction `.deb` et la suite protégée
par Xvfb/Openbox décrites dans la section anglaise. Les tests ne doivent pas modifier la base
de paquets du système. Les pull requests doivent décrire l’impact utilisateur, la compatibilité,
la sécurité et les limites connues.

[Retour au début](#top)
