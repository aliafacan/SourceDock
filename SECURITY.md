<div align="center">

<a id="top"></a>
[🇬🇧 English](#english) &nbsp;•&nbsp; [🇹🇷 Türkçe](#turkish) &nbsp;•&nbsp; [🇩🇪 Deutsch](#german) &nbsp;•&nbsp; [🇪🇸 Español](#spanish) &nbsp;•&nbsp; [🇧🇷 Português (BR)](#portuguese) &nbsp;•&nbsp; [🇫🇷 Français](#french)

</div>

---

<a id="english"></a>
# 🇬🇧 SourceDock Security Policy

## Reporting a vulnerability

Please report suspected security vulnerabilities privately to
[aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com). Do not open a public
issue, pull request, or discussion for an unpatched vulnerability.

Include, when safe to do so:

- The affected SourceDock version or commit.
- Distribution, desktop environment, and relevant provider/package format.
- A concise description of the impact and attack prerequisites.
- Reproduction steps or a minimal proof of concept.
- Relevant logs or screenshots after removing passwords, tokens, private keys,
  usernames, home-directory paths, and other personal data.

Please do not send credentials or a malicious sample unless it is necessary and
you have agreed on a safe transfer method first.

Reports are handled confidentially as practical. Response and remediation times
depend on maintainer availability; this project does not promise a fixed service
level or a guaranteed disclosure timeline.

## Scope

Security reports are especially useful for issues involving:

- Package command construction, authorization, or privilege boundaries.
- Archive extraction, portable ownership, or path traversal.
- Credential handling, logging, redaction, or local history.
- Desktop integration, local metadata parsing, or untrusted package files.
- Update downloads, checksum verification, or release authenticity claims.

The project’s own infrastructure, third-party package repositories, and unrelated
upstream software are outside SourceDock’s direct control. They may still be
mentioned so that the correct maintainer can be contacted.

## Current security boundaries

- SourceDock is intended to run as the normal desktop user. Native package
  operations request limited administrative access; the GUI must not run as root.
- Credentials are handled in memory, passed to the authorized operation through
  standard input, redacted from diagnostics, and cleared after the configured
  lifetime.
- Local files are not treated as trusted merely because they are present on disk.
  AppImage inspection does not execute the file, and installed AppImages are not
  guaranteed to be sandboxed.
- The release SHA-256 file verifies download integrity only. It is not a digital
  signature and does not authenticate a publisher or signer.
- Automated tests use disposable directories and mocked privileged commands; they
  are not intended to modify the host package database.

For implementation details, see [Authorization](docs/AUTHORIZATION.md) and the
relevant tests under `tests/`.

## Supported versions

Security fixes are applied to the current development line. Users should upgrade
to the latest published release where possible. Backports to older versions are
evaluated case by case and are not guaranteed.

[Back to top](#top)

---

<a id="turkish"></a>
# 🇹🇷 SourceDock Güvenlik Politikası

## Güvenlik açığı bildirimi

Şüpheli güvenlik açıklarını [aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com)
adresine özel olarak bildirin. Yaması yayımlanmamış bir açığı public issue, pull request
veya tartışma olarak paylaşmayın.

Mümkün ve güvenliyse etkilenen sürüm/commit, dağıtım ve masaüstü ortamı, etki açıklaması,
ön koşullar, yeniden üretme adımları ve kişisel verilerden arındırılmış logları ekleyin.
Şifre, token, özel anahtar, kullanıcı adı veya kişisel dosya yollarını silin. Kimlik bilgisi
veya zararlı örnek göndermeden önce güvenli aktarım yöntemini kararlaştırın.

Bildirimler mümkün olduğunca gizli incelenir; yanıt ve düzeltme süreleri için garanti edilen
bir hizmet seviyesi yoktur.

## Kapsam ve sınırlar

Paket komutları ve yetkilendirme, arşiv çıkarma ve yol geçişi, kimlik bilgileri ve loglar,
masaüstü entegrasyonu, güvenilmeyen yerel dosyalar, güncelleme indirmeleri ve checksum
doğrulaması kapsam dahilindedir.

SourceDock normal masaüstü kullanıcısı olarak çalışmalıdır; GUI root olarak çalıştırılmamalıdır.
Yerel dosyalar otomatik olarak güvenilir kabul edilmez, AppImage incelemesi dosyayı çalıştırmaz
ve SHA-256 dosyası yalnızca bütünlük doğrular; dijital imza veya yayıncı doğrulaması değildir.

Güvenlik düzeltmeleri mevcut geliştirme hattına uygulanır. Kullanıcıların mümkün olduğunda
en son yayımlanan sürüme geçmesi önerilir; eski sürümlere geri taşıma garanti edilmez.

[Başa dön](#top)

---

<a id="german"></a>
# 🇩🇪 Sicherheitsrichtlinie von SourceDock

Melde vermutete Sicherheitslücken vertraulich an
[aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com). Erstelle für eine ungepatchte
Lücke kein öffentliches Issue, keine Pull Request und keine Diskussion.

Gib nach Möglichkeit Version oder Commit, Distribution, Desktop-Umgebung, Auswirkungen,
Voraussetzungen, Reproduktionsschritte und bereinigte Logs an. Entferne Passwörter, Tokens,
private Schlüssel, Benutzernamen und persönliche Pfade. Sende keine Zugangsdaten oder
Schadproben ohne vorher vereinbarten sicheren Übertragungsweg.

Der Schwerpunkt liegt auf Paketbefehlen und Berechtigungen, Archivextraktion und Pfaden,
Anmeldedaten und Protokollen, Desktop-Integration, lokalen Dateien sowie Downloads und
Prüfsummen. SourceDock läuft als normaler Desktop-Benutzer; die GUI darf nicht als root
laufen. SHA-256 bestätigt nur die Integrität des Downloads, keine Signatur oder Herkunft.

Meldungen werden so vertraulich wie praktisch möglich behandelt. Es gibt keine garantierte
Antwort- oder Behebungsfrist. Sicherheitsfixes gelten primär für die aktuelle Entwicklungslinie.

[Zum Anfang](#top)

---

<a id="spanish"></a>
# 🇪🇸 Política de seguridad de SourceDock

Envía las vulnerabilidades sospechadas de forma privada a
[aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com). No abras un issue, pull request
ni debate público para una vulnerabilidad sin corregir.

Incluye, cuando sea seguro, la versión o commit afectado, distribución, entorno de escritorio,
impacto, requisitos previos, pasos de reproducción y logs sin datos personales. Elimina
contraseñas, tokens, claves privadas, nombres de usuario y rutas personales. No envíes
credenciales ni muestras maliciosas sin acordar un método seguro.

El alcance incluye comandos de paquetes y permisos, extracción de archivos, rutas, credenciales,
logs, integración de escritorio, archivos locales, descargas y verificaciones de checksum.
SourceDock debe ejecutarse como usuario normal; la GUI no debe ejecutarse como root. SHA-256
verifica la integridad de la descarga, no una firma ni la identidad del publicador.

Los informes se gestionan con la mayor confidencialidad posible, sin garantía de plazos fijos.
Las correcciones se aplican principalmente a la línea de desarrollo actual.

[Volver al inicio](#top)

---

<a id="portuguese"></a>
# 🇧🇷 Política de segurança do SourceDock

Envie suspeitas de vulnerabilidade em privado para
[aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com). Não abra uma issue, pull request
ou discussão pública para uma vulnerabilidade ainda não corrigida.

Quando for seguro, inclua a versão ou commit afetado, distribuição, ambiente de desktop,
impacto, pré-requisitos, passos de reprodução e logs sem dados pessoais. Remova senhas,
tokens, chaves privadas, nomes de usuário e caminhos pessoais. Não envie credenciais ou
amostras maliciosas sem combinar um método seguro.

O escopo inclui comandos de pacotes e autorização, extração de arquivos, caminhos,
credenciais, logs, integração de desktop, arquivos locais, downloads e verificações de
checksum. O SourceDock deve rodar como usuário normal; a GUI não deve rodar como root.
SHA-256 verifica apenas a integridade do download, não uma assinatura ou o publicador.

Os relatos são tratados com a maior confidencialidade possível, sem prazo fixo garantido.
As correções são aplicadas principalmente à linha de desenvolvimento atual.

[Voltar ao início](#top)

---

<a id="french"></a>
# 🇫🇷 Politique de sécurité de SourceDock

Signalez les vulnérabilités présumées en privé à
[aliafacan.dev@gmail.com](mailto:aliafacan.dev@gmail.com). N’ouvrez pas d’issue, de pull
request ou de discussion publique pour une vulnérabilité non corrigée.

Lorsque c’est possible, indiquez la version ou le commit, la distribution, l’environnement
de bureau, l’impact, les prérequis, les étapes de reproduction et des journaux nettoyés.
Retirez mots de passe, tokens, clés privées, noms d’utilisateur et chemins personnels. N’envoyez
pas d’identifiants ni d’échantillon malveillant sans méthode de transfert sûre convenue.

Le périmètre couvre les commandes de paquets et l’autorisation, l’extraction d’archives, les
chemins, les identifiants, les journaux, l’intégration de bureau, les fichiers locaux, les
téléchargements et les sommes de contrôle. SourceDock doit fonctionner comme utilisateur
normal ; l’interface ne doit pas fonctionner en root. SHA-256 vérifie uniquement l’intégrité
du téléchargement, pas une signature ni l’identité de l’éditeur.

Les signalements sont traités de manière aussi confidentielle que possible, sans délai garanti.
Les correctifs s’appliquent principalement à la ligne de développement actuelle.

[Retour au début](#top)
