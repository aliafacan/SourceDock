# Roadmap Implementation Report

> [!NOTE]
> **Historical Report (2026-10-14):** This document records an earlier implementation status. For current 1.3.0 release status, see [README.md](../README.md) and [COMPATIBILITY.md](COMPATIBILITY.md).

Historical report date: 2026-10-14. For the 2026-10-16 source audit, checklist,
new fixes and current validation, see [Roadmap Completion Report](ROADMAP_COMPLETION_REPORT.md).

Prepared version: 1.3.0. Existing user edits and older tracked
package artifacts were preserved. No host applications were installed, removed or
updated during implementation. No GitHub release, topic, discussion or external
announcement was published.

## Completed Locally

| Roadmap area | Implementation | Evidence |
| --- | --- | --- |
| P0.1 Portable removal | Matching registry/manifest/root, shortcut restrictions, reported I/O errors | Adversarial temporary-folder tests |
| P0.2 Extraction | Relative paths, link/special-file rejection, member/size/ratio limits, staging and rollback | Traversal, links, bomb and failed-upgrade tests |
| P0.3 AppImage | Non-executing filename/ELF inspection, no preview chmod | Script-marker and permission regression test |
| P0.4 Commands | Nonblocking deadlines, process-group cleanup, credential clearing/redaction, critical cancellation restrictions, serialization | Silent process, SIGTERM resistance, authentication and UI process tests |
| P0.5 Trust | Unknown/unverified source labels, access information, explicit file-source confirmation, APT simulation | Installer and preview tests |
| UI shell | Sidebar, compact mode, global search, symbolic icons, reusable states | Whole-window and navigation tests |
| Discover/details | Application-first cards, categories, source-scoped installed state, exact identities, grouped provider variants, source chooser and optional AppStream fields/gallery | Identity, metadata, source-grouping and error-state tests |
| Installed/updates | Separate system packages, compact/advanced table, summary cards, grouped update selection, firmware warnings and selection bar | Package callbacks and update/confirmation tests |
| Installer/operations | Independent preview, worker metadata, trust gate, actual completion/cancellation, redacted history | Installer, history and process tests |
| Settings/help | System/Light/Dark, live TR/EN, scale, preferred source, startup check, current help | Locale/theme tests and screenshots |
| P2 export/import/sources | Versioned export, conservative restore preview, explicit remote, read-only sources | Roundtrip, mismatch and malicious-ID tests |
| Packaging/docs | Single version, minimum Python 3.10, optional providers, desktop/AppStream checks, checksum, full GPL, draft workflow | Local build, Ruff and package metadata validation |
| SourceDock rebrand | Canonical SourceDock command/package/desktop/icon identity with one-release VoltApp compatibility aliases and data-path migration | Source tree scan, package metadata and compatibility tests |

## Verification

- `unittest discover`: 106 tests passed under an isolated Xvfb display.
- Ruff correctness/security-oriented rule set passed.
- Desktop Entry and AppStream validation passed; AppStream reports a nonfatal
  uppercase-component-ID pedantic hint.
- GPL-3 text compares exactly with `/usr/share/common-licenses/GPL-3`.
- Real Zorin catalog reading loaded 122 applications and 2882 packages; dark/light TR/EN screenshots were captured.
- The real-data visual matrix covered 48 theme/language/scale/size combinations with no clipped controls. A controlled 1000-record render benchmark completed in 44.24–87.40 ms.
- Store search now hides implementation-only native packages from the application surface while keeping them in System Packages. A package exposed by multiple providers is one card with provider selection in its detail dialog.
- The latest geometry/performance results are machine-readable in
  `screenshots/validation.json`; fixture performance data is explicitly identified.
- Earlier verification caught a missing startup callback and a GTK foreach callback
  signature error. Both were reproduced, corrected and covered by regression tests.

The final package and screenshot matrix were regenerated after code review. This
report does not substitute local results for remote CI or real package transactions.

## Remaining Evidence and Later Work

- Clean installation/removal and real provider transactions on disposable Zorin,
  Ubuntu, Debian, Fedora, openSUSE and Arch environments.
- Remote CI execution, tag creation, draft review, publication and community setup.
- Enabled GNOME Shell integration runtime test. The current desktop extension is
  disabled, and a user-installed copy shadows the system copy.
- A production Polkit helper/policy, independently audited and tested before rollout.
- Optional tray/background notifications, Timeshift/Btrfs snapshot integration and
  additional language contribution infrastructure.
- Provider-supported architecture filtering and expanded catalog metadata where
  those data are available. Unknown architecture/trust/popularity is not fabricated.
- Complete safety-aware unused-package cleanup with a provider plan and exact target
  confirmation; existing cleanup commands must receive a separate transaction review.

## Manual Acceptance

1. Install the prepared .deb with APT and launch from both terminal and application menu.
2. Visit every navigation item; use global search; inspect source filters and details.
3. Select update entries and cancel firmware confirmation without changing the device.
4. Open a local package, inspect the trust/access and simulation panels, then cancel.
5. Toggle TR/EN, System/Light/Dark and scale; inspect compact navigation and focus.
6. Export/import an application list and review targets without confirming installation.
7. Inspect software sources and history; verify no repository mutation occurs.
8. Activate the refreshed GNOME extension after session reload and inspect app context actions.

Design decisions and reference links: [UI Design](UI_DESIGN.md).
Platform evidence: [Compatibility](COMPATIBILITY.md).
Authorization boundary: [Authorization](AUTHORIZATION.md).
