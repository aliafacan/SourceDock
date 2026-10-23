# Changelog

## 1.4.1 - 2026-10-23

### UI & Provider Reliability
- Treat the visible header search field as the Store search source of truth while keeping the hidden page-local field as an internal mirror.
- Update UI workflow coverage for page-scoped search restoration and Enter-submitted Store searches.
- Verify provider failures through the new per-source status summary and unavailable source labels without duplicating raw timeout errors.

### Documentation & Verification
- Add a periodic, non-blocking GitHub Releases check with a localized update notification.
- Let the notification download and checksum-verify the matching DEB before opening the existing package preview and authorization flow.
- Use the latest current APT installation date after a package is removed and installed again.
- Update the Ubuntu 22.04/24.04 CI evidence to the current 295-test suite.
- Align installation instructions and package references with the 1.4.1 GitHub release assets.

## 1.4.0 - 2026-10-23

### Localization
- Add German, Spanish, Brazilian Portuguese and French catalogues alongside Turkish and English.
- Move runtime translations to six parity-checked JSON catalogues with English fallback and placeholder validation.

### Performance & Reliability
- Add staged installed-application discovery, persistent inventory caching and source-aware partial results.
- Keep last-known source entries when an optional provider times out, with clearer diagnostics instead of losing the whole list.
- Add store search caching, provider status reporting and responsive first-result rendering.

### UI & Updates
- Make update filters load update metadata on demand while keeping the complete installed inventory stable.
- Improve update group selection, source filtering, installed-app layouts and search interactions.
- Fix provider response races, stale update results and incorrect installed-application totals.

## 1.3.0 (Release Candidate 1) - Unreleased

### Security & Transaction Stability
- **Non-blocking Pipe I/O**: Resolved potential background stream pipe deadlocks using `select.select` for interleaved stdout/stderr draining.
- **Accurate Exit Status**: Prevented streaming operations from prematurely registering a success code (`0`) on abrupt process termination.
- **Cross-Runner Concurrency Coordination**: Enforced file-level locking (`flock`) across distinct `CommandRunner` instances alongside global transaction mutexes to prevent race conditions during native package manager operations.
- **Credential Lifecycle & Redaction**: Strict in-memory credential caching with 15-minute TTL and automatic sanitization of passwords and user home paths in error output and operation logs.

### UI Lifecycle & Responsiveness
- **Lingering Process Log Streaming**: Maintained stdout/stderr streaming to open dialogs during extended or lingering background draining.
- **Delayed Callback Guards**: Protected GTK window closing against delayed `GLib.idle_add` invocations, preventing duplicate finish notifications or calls on destroyed widgets.
- **Exception Scoping**: Resolved Python 3 exception variable unbinding across installer and store views.

### Packaging, Branding & Compatibility
- **SourceDock Rebrand**: Full rename of the application, repository, desktop metadata, icons, and Debian package from VoltApp to SourceDock.
- **Backward Compatibility**: Seamless upgrade path via Debian control directives (`Replaces: voltapp`, `Breaks: voltapp (<< 1.3.0)`, `Provides: voltapp`), retaining `voltapp` CLI alias and preserving user settings. (Note: End-to-end upgrade verification from an existing VoltApp installation remains pending disposable VM testing).
- **System Verification**: Verified on Zorin OS 18.1 (real host installation, UI navigation, and `apt` install/remove test lifecycle); the current Ubuntu 22.04 & 24.04 CI matrix runs 295 tests under Xvfb/Openbox.

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
