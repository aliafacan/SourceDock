# Changelog

## 1.3.0 - 2026-10-14 (SourceDock Rebrand)

- Rename the public application, repository content, desktop identity, icon name and Debian package to SourceDock.
- Keep `voltapp` as a compatibility command and MIME desktop alias during the migration release.
- Migrate preferences and portable/history data paths without discarding existing VoltApp data.

## 1.2.0 - 2026-10-14 (Prepared Locally)

- Add responsive sidebar navigation, global search, GTK symbolic actions and neutral theme tokens.
- Add System/Light/Dark themes and retain TR/EN and 90/100/110/125 percent scale.
- Add discovery cards, table mode, categories, explicit source identity and local AppStream metadata.
- Add unified updates grouped into applications, system, firmware and runtimes, with firmware confirmation.
- Add read-only software sources and versioned application-list restoration previews.
- Add bounded, redacted operation history, export and clearing.
- Harden portable ownership, archive paths/links/limits and transactional archive replacement.
- Stop executing AppImage files during metadata inspection.
- Fix streaming timeouts, credential lifetime, critical cancellation and external process controls.
- Keep local package inspection off the GTK thread and show trust/access and APT simulation.
- Fix missing callback and translation regressions; add startup, workflow and adversarial tests.
- Align Python/GI CI, package versioning, desktop/AppStream validation and SHA-256 output.
- Replace the former character-based icon with an original lightning mark and include full GPLv3 text.

## 1.1.2

- Complete package row/detail/remove callbacks and verify main-window startup.

## 1.1.1

- Bump the package version so APT installs the newly built files.

## 1.1.0

- Application details and desktop action integration.
