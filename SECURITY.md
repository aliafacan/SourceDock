# SourceDock Security Policy

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
