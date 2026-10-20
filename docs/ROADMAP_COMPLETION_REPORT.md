# SourceDock Roadmap Follow-Up

> [!NOTE]
> **Historical Report (2026-10-16):** This document records an earlier roadmap follow-up checkpoint. For current 1.3.0 release status, see [README.md](../README.md) and [COMPATIBILITY.md](COMPATIBILITY.md).

Date: 2026-10-16. Source version: 1.3.0. Scope: the current dirty working tree,
not the remote GitHub revision. Existing local changes and historical screenshots
were preserved. No commit, push, tag, release, host package transaction or firmware
write was performed. No old screenshots were repackaged as a new showcase.

Turkce ozet: Yol haritasinda 113 madde tikli, 54 madde gerekcesiyle acik/kismi.
Son devam turunda host test korumasi, bagimsiz islemler ve performans kabulune
odaklanildi. 193 test gecti. Gercek VM kurulum,
GNOME oturumu ve uzak CI kabulu tamamlanmadigi icin yayin hazirligi kanitlanmis degil.

## Checklist Accounting

`archive/SOURCEDOCK_CODEX_ROADMAP_UI.md` is now the task-by-task status source:

- 113 checked entries: 109 from the initial pass and four in the continuation.
- 54 unchecked entries, each with a specific partial, open, blocked or untested note.
- Checked implementation entries do not imply a successful real package transaction.
- Several entries contain multiple requirements. They remain unchecked when only
  some requirements have evidence. Optional P2 features remain visible as open work.

The previous assistant summary incorrectly said portable/archive security was
unimplemented. The manifest/root checks, bounded extraction and staging/rollback
were already present. They were retained and verified rather than rewritten.

## Current Continuation Results

This section supersedes the initial 180-test result below. No new showcase ZIP or
screenshot collection was produced. The four new checkmarks cover the guarded
CI test entry point, full synthetic list interaction measurements, and read-only
verification of the existing GitHub Releases/topics state. They do not mean a
release was created or topics were populated.

### Implemented And Verified

- `tools/run_tests.py` installs a Python audit hook before test discovery. Real
  package-manager, privilege-helper, shell and unknown command executions fail
  closed. The run also fails if application code swallows a blocked-command
  exception. XDG data/config/cache, GSettings and test temporary files are isolated.
- Required read exceptions are explicit: `.deb` metadata, version comparison,
  the X11 WM probe and test-owned desktop caches. Python fixture children remain
  allowed. This is a trusted-test accident guard, **not an OS sandbox** for hostile
  Python children or native libraries. Real acceptance still requires VMs.
- Live sentinel tests prove the rejected executable never starts. Direct commands,
  shell execution, `os.system` and `os.posix_spawn` are covered without touching a
  real package manager. The supported CI/developer commands use the guarded entry.
- Both workflows install Openbox and x11-utils on disposable CI runners and wait
  for a functioning WM. They do not silently rely on Xvfb alone for geometry tests.
- Standalone update/remove now run in workers and deliver results through GLib.
  GTK can process a heartbeat before the fake operation completes; repeated clicks
  are gated. Auth prompts stay on GTK, passwords are cleared after each attempt,
  cancellation does not retry, purge is preserved, failures retain the details
  window, and operation history records the outcome. Closing during an active
  operation does not immediately quit its main loop.
- The desktop `--uninstall` entry uses the same sensitive-package confirmation
  and asynchronous operation path. Legacy/self manual-uninstall script handling
  is retained. Entry-point tests verify this routing with fake registries; they
  are not evidence of a real package removal or GNOME Shell acceptance.
- Flatpak icon lookup resolves AppStream generation directories once per remote
  and architecture instead of repeating that glob for every size/name/extension.
  Application/remote names containing path or glob syntax are rejected. Existing
  exported, hashed and installed icon resolution tests still pass.

### Test Status

| Check | Status | Evidence |
| --- | --- | --- |
| Full guarded suite, isolated 1366x768 Xvfb + Openbox | PASS | 193 tests; 0 failures/errors/skips; 12.114 s; 39 allowed command calls, 0 unexpected blocked attempts |
| Ruff | PASS | `ruff check .`: All checks passed |
| compileall | PASS | `main.py sourcedock tests tools` |
| Whitespace and shell syntax | PASS | `git diff --check`; `bash -n` on build/install/uninstall/X11 scripts |
| Fresh package build and metadata inspection | PASS | New package below, tested via explicit `SOURCEDOCK_TEST_DEB`; never installed |
| Desktop Entry and offline AppStream validation | PASS | Both validators ran during package build; existing non-blocking category hint remains |
| 1,000-row interaction acceptance | PASS | Four physical Xvfb root/font-scale combinations, five measured iterations after one warmup each |
| Current uncommitted tree on GitHub CI | NOT TESTED | No push/PR was performed |
| Clean .deb/VoltApp migration and real provider transactions | BLOCKED | No disposable VM acceptance evidence; no host transactions run |
| Real GNOME Shell 46 session integration | NOT TESTED | Unit-tested CLI routing is not extension/session acceptance |

Initial failures are retained, not counted as successful tests:

- The first sandboxed focused run had four GTK tests skipped because its Xvfb
  display was inaccessible. Retrying with isolated-display access passed all seven.
- An icon-scan regression test initially matched an installed-icon glob as though
  it were an AppStream generation glob. The assertion was narrowed to the actual
  AppStream pattern; the final complete suite passes.
- Two initial performance runs are **FAIL** in their original JSON files. The
  harness required a scrollbar upper limit sampled before GTK completed row
  measurement. It now verifies a real draw with the final row in the visible
  range. Old failed evidence is preserved; only `performance-final/` is accepted.

### Measured Interaction Latency

All numbers below are first GTK draw p95 in milliseconds, including the local
SearchEntry delay. Populate/search/source-filter/category-filter/scroll budgets
were set to 1000/350/250/250/50 ms before these successful runs. No provider query
or real installation is part of this synthetic benchmark.

| Physical X11 root | App font scale | Initial model setup | Populate | Search | Source Filter | Category Filter | Scroll |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1024x768 | 100% | 1486.5 | 89.2 | 185.5 | 69.1 | 52.1 | 24.9 |
| 1024x768 | 125% | 1317.9 | 61.4 | 180.3 | 46.5 | 40.8 | 17.4 |
| 1366x768 | 100% | 1260.7 | 64.2 | 181.7 | 48.5 | 41.7 | 17.5 |
| 1366x768 | 125% | 1312.2 | 66.5 | 180.6 | 47.4 | 41.8 | 17.5 |

Initial setup includes construction, first model and cold icon lookup; it is not
silently folded into warmed population samples. Each JSON also includes handler,
warmup and iteration times. Scroll means programmatic scrolling until row 999 is
visible, not hardware-wheel latency or smooth GPU FPS. These are application font
scales on X11, not compositor fractional-scaling certification. No comparable
pre-change end-to-end benchmark exists, so no numerical speedup is claimed.

### Read-Only GitHub Verification

The repository and releases APIs were read on 2026-10-16. Releases returned `[]`,
topics returned `[]`, Issues is enabled and Discussions is disabled. No remote
setting or content was changed. The most recent
[successful CI run](https://github.com/aliafacan/SourceDock/actions/runs/38545352107)
is for `13f6f0b45fee361382ebf3ab87ae8fa7e3f13c58`, the local base commit, dated
2026-10-14. It cannot verify any of the dirty working-tree changes in this report.
Sources: [repository API](https://api.github.com/repos/aliafacan/SourceDock),
[releases API](https://api.github.com/repos/aliafacan/SourceDock/releases?per_page=100).

### Continuation Files And Artifacts

Files changed in this continuation (other pre-existing dirty files were preserved):

- `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/pull_request_template.md`
- `main.py`, `sourcedock/ui/components/app_details_dialog.py`, `sourcedock/ui/components/progress.py`
- `sourcedock/core/icons.py`, `tools/test_guard.py`, `tools/run_tests.py`, `tools/ui_performance.py`
- `tests/test_host_guard.py`, `tests/test_standalone_actions.py`, `tests/test_sources_and_icons.py`
- `README.md`, `CONTRIBUTING.md`, `tests/README.md`, `archive/SOURCEDOCK_CODEX_ROADMAP_UI.md`, this report

Evidence root: `/tmp/sourcedock-roadmap-followup-20261016/`.
`final-tests.log` is the complete guarded run; `performance-final/*.json` and
matching logs contain the four accepted measurements. Earlier `performance/` and
`performance-fixed/` failures are retained for traceability.

Fresh artifact: `final-package/sourcedock_1.3.0_all.deb`.
SHA-256: `4d396fdda7035b10c967eceadbcb4dc3c63cf7299225548d9a0151a4a0ac2e22`.
This artifact is **built and inspected, not installed or release-certified**.
Remaining local product/test work is still enumerated by the 54 unchecked roadmap
entries; the remainder is not solely a VM/environment problem.

## Initial Pass Changes (Historical)

| Area | Result | Evidence |
| --- | --- | --- |
| Targeted APT removal | Purging a selected package no longer silently invokes autoremove for unrelated packages | Fake-runner removal regressions |
| Flatpak data removal | Reject invalid IDs, symlink ancestry and non-directory targets before uninstall; recheck after uninstall; report cleanup failures | Temporary-file adversarial tests |
| Sensitive package removal | Single, bulk and standalone confirmation require the sensitive package names; the details callback no longer opens duplicate confirmations | GTK confirmation and existing removal workflows |
| Portable removal | A shortcut deletion failure leaves the installation and manifest available for retry | Injected permission failure and successful retry |
| Password handling | Streaming command/error arguments redact the known password | Fake command and OSError regressions |
| Transaction serialization | Mutating commands are serialized; read-only provider queries remain concurrent | Critical/read-only command classification tests and live catalog timing |
| Flatpak cleanup | Read-only libflatpak unused-ref plan, explicit user/system scope preview, cancellation, stale-plan recheck and exact `--no-related` targets | Fake-runner plan tests; real read-only plan returned no unused refs |
| Provider feedback | Informational system updates use `provider_notices`, not provider failures | Snapshot and GTK notice/translation tests |
| Checkbox selection | Select-all reflects empty, full and partial selection; unsupported targets remain excluded | GTK selection regression |
| Narrow update headers | Long version headings ellipsize within their own column and retain full tooltips | Actual 1024x768/125 root screenshot |
| Partial update failures | Measured state is refreshed after failure; retry skips completed targets | Failure-refresh and per-item retry tests |
| Updates changelog | APT update items expose their changelog through the pointer/keyboard context menu | Existing asynchronous changelog path; real provider execution remains read-only |
| Dialog queries | Permissions, version history and changelog queries load in workers; cancelling a loader suppresses late results | GTK worker/cancellation regression |
| Independent windows | Installed details and help no longer call `Gtk.Dialog.run()`, which would temporarily make them modal again | Call-site regression; existing transient/modal property tests |
| Localization/help | Diagnostic summaries/details and history headers/actions refresh with language; F1 opens the current page topic first | TR/EN and help-context tests |
| Installed trust information | Show known publisher metadata without treating it as signature verification; Snap uses its own signature explanation | Source-specific code inspection and GTK construction tests |
| History privacy | Existing history is redacted when read/exported, including other home-directory usernames | Legacy export regression |
| MIME tests | A custom desktop destination no longer installs icons into the user's real home | Test asserts no icon-install call |
| Manual uninstall | When old and new manual installations coexist, removing the legacy files no longer skips the SourceDock installation | Shell syntax and branch inspection; real lifecycle still untested |
| Packaging | Package copyright attribution, complete GPL, original LICENSE and third-party notices are included; optional libflatpak GIR is suggested | Built `.deb`, document inspection, checksum and validators |
| CI/release preparation | Build before tests; inspect the explicitly selected new artifact; reject a release tag that differs from APP_VERSION | Local workflow inspection; no remote CI claim |
| X11 acceptance | Fit the measured outer frame, retain CSD borders, capture physical root pixels, measure unadjusted dialogs and reject overflow | Actual Xvfb/Openbox geometry tests and matrices |

## Initial Pass Verification (Historical)

| Check | Status | Result |
| --- | --- | --- |
| Complete test suite under isolated Xvfb + Openbox | PASS | 180 tests, 0 failures, 0 errors, 0 skipped; 12.530 s |
| Delivered `.deb` read-only inspection | PASS | Explicit SOURCEDOCK_TEST_DEB; name/version/architecture/metadata test passed |
| Ruff | PASS | All checks passed |
| compileall | PASS | main.py, sourcedock, tests, tools |
| Shell syntax | PASS | build, install, uninstall and X11 runner |
| git diff --check | PASS | Existing and current changes pass whitespace validation |
| Desktop Entry validation | PASS | Non-blocking additional-category hint remains |
| AppStream offline validation | PASS | Validation successful |
| `.deb` build and SHA-256 | PASS | Package built in /tmp; checksum verified |
| Real X11 1024x768 matrix | PASS | 24 theme/language/scale cases, 0 geometry failures |
| Real X11 1366x768 matrix | PASS | 24 theme/language/scale cases, 0 geometry failures |
| Real X11 1920x1080 | PASS | Additional light/en/125 case; this is not a full 1920 matrix |
| libvirt connection | PASS | qemu:///system responds with an empty VM list |
| Real package install/upgrade/remove/purge | BLOCKED | No disposable VM is defined |
| Real APT/Flatpak/Snap transactions | BLOCKED | No reviewed disposable transaction environment |
| GNOME Shell 46 integration | NOT TESTED | No enabled-extension session acceptance was performed |
| GitHub CI on current changes | NOT TESTED | Local dirty changes were not pushed |
| Lintian | BLOCKED | Tool unavailable; no host dependency was installed |
| Full keyboard/Orca/compositor HiDPI acceptance | NOT TESTED | GTK tests are not an accessibility/compositor certification |

No test skip is included in the 180 successful tests. Existing GTK/Gdk deprecation
warnings are not counted as failures or hidden. Backend parsing tests still do
not cover every locale and provider failure combination; the checklist says so.

## Physical Measurements

The full small-screen matrix covers dark/light/system, TR/EN and 90/100/110/125
application font scales. `GDK_SCALE=1` is explicit: these are physical X11 root
pixels, not proof of fractional scaling under every desktop compositor.

| Root/workarea | Fitted outer frame | GTK client | Light/EN settings at 125% | Installer outer frame |
| --- | --- | --- | --- | --- |
| 1024x768 | 1024x768 | 1014x698 | 722x633 | 522x485 |
| 1366x768 | 1366x768 | 1356x698 | 722x633 | 522x485 |

Details dialogs measured 682x585 in the final full matrix. Main titlebar and
sidebar, fixed action controls and unadjusted details/installer/settings dialogs
were measured against the actual workarea. Each scenario includes full root PNG
proof. Scrollable content is identified separately from fixed controls.

The earlier 1034x778 result came from the showcase sizing routine adding a 10px
CSD border to the requested 1024x768 content crop. Normal startup already fitted
the workarea. The routine now corrects both measured outer dimensions. It does
not resize a failing modal to hide a natural overflow.

## Catalog And Performance Observations

During this turn an overly broad new transaction lock briefly serialized read-only
provider queries. The earlier geometry run still fitted, but its catalog contained
only 3-7 applications with provider timeout errors. That run is retained as
diagnostic evidence and is not the final catalog acceptance result.

After classifying read-only queries separately, a clean live run returned 122
applications in 2042.7 ms, with all six providers complete and no provider errors.
The final full matrices read 120 applications, 2914 native packages and 80 search
results without provider errors in their isolated environment. The runner also
cleans an inherited Snap XDG_DATA_HOME to match production launcher behavior.
Catalog timings/counts are observations from their recorded environments, not a
controlled speedup claim or an invented stable application count.

The additional source-matched cold-cache run returned 95 applications and
`flatpak: timeout after 5s` on both roots. Geometry passed; complete Flatpak catalog
availability did not. The timeout remained an explicit source warning and was not
passed off as a complete catalog. This intermittent availability still needs
VM/network acceptance. The final current-x11 checks, after the last header
adjustment, returned 122 applications and no provider errors on both roots. Their
independent runner validation and complete-root PNG checks passed. Earlier
intermittent timeout evidence is retained rather than hidden by successful retries.

Controlled 1000-record model population samples in the final matrices:

- 1024 root: 48.84, 33.12, 33.34 ms.
- 1366 root: 47.96, 32.97, 33.05 ms.

These measure model population, not scroll FPS or end-to-end search latency.
The broader performance checklist entry remains partial.

## Reproduction And Evidence

Evidence directory: `/tmp/sourcedock-roadmap-20261016/`.

| Evidence | Path |
| --- | --- |
| Full tests | final-tests.log |
| Delivered package metadata test | delivery-inspection.log |
| 1024 full matrix + root PNGs | final-x11/1024x768/validation.json and runner-validation.json |
| 1366 full matrix + root PNGs | final-x11/1366x768/validation.json and runner-validation.json |
| Additional 1920 case | 1920x1080/validation.json |
| Snap-data-home matched final checks | source-matched-x11/ |
| Latest header/layout and delivered-source checks | current-x11/ |
| Delivered package and checksum | delivery-package/sourcedock_1.3.0_all.deb and .deb.sha256 |

Delivered package SHA-256:
`06ff2fa604f60e0218a9a8a7cd1f67bafaaf74650b8bc136d2c7920974e253d8`.

The delivered package also includes the final contextual-help and update-menu
changes, covered by the 180-test run. Its separate metadata inspection is recorded
explicitly; metadata inspection is not installation evidence.

See `tests/README.md` for separate backend/security, GTK, physical-root and VM
acceptance commands. Re-run with a fresh output directory:

```bash
SOURCEDOCK_TEST_PACKAGE=/tmp/sourcedock-roadmap-20261016/delivery-package/sourcedock_1.3.0_all.deb \
  bash tools/run_acceptance_x11.sh
```

## Files Changed In This Turn

This list excludes unrelated pre-existing dirty files and screenshots:

```text
archive/SOURCEDOCK_CODEX_ROADMAP_UI.md
.github/workflows/ci.yml
.github/workflows/release.yml
THIRD_PARTY_NOTICES.md
packaging/build_deb.sh
uninstall.sh
sourcedock/backend/manager.py
sourcedock/backend/mime_integration.py
sourcedock/backend/portable.py
sourcedock/backend/flatpak_cleanup.py
sourcedock/core/history.py
sourcedock/core/models.py
sourcedock/core/process.py
sourcedock/core/runner.py
sourcedock/i18n.py
sourcedock/theme.py
sourcedock/ui/components/common.py
sourcedock/ui/components/removal.py
sourcedock/ui/components/app_details_dialog.py
sourcedock/ui/views/help_view.py
sourcedock/ui/views/installed_view.py
sourcedock/ui/views/operations_view.py
sourcedock/ui/views/packages_view.py
sourcedock/ui/views/updates_view.py
sourcedock/ui/window.py
tests/README.md
tests/test_flatpak_cleanup.py
tests/test_help_and_tooltips.py
tests/test_metadata_and_history.py
tests/test_mime_integration.py
tests/test_safety.py
tests/test_stage4.py
tests/test_ui_workflows.py
tests/test_window_startup.py
tests/test_window_surfaces.py
tests/test_ui_smoke_geometry.py
tools/ui_smoke.py
tools/run_acceptance_x11.sh
docs/ROADMAP_IMPLEMENTATION.md
docs/RELEASE_ACCEPTANCE_ENVIRONMENT.md
docs/ROADMAP_COMPLETION_REPORT.md
```

## Remaining Work And Release Decision

**SourceDock 1.3.0 is not yet proven release-ready.** The 58 open checklist entries
include both external acceptance and implementable product work; they are not
all attributed to missing infrastructure.

Release evidence still needed: clean `.deb` lifecycle and VoltApp migration,
provider transactions in disposable VMs, real GNOME extension/session acceptance,
remote CI, complete third-party license review and accessibility/HiDPI acceptance.

Open local work includes a reviewed Polkit prototype/policy, broader provider
locale/error fixtures, complete formatter/security scanning policy, a process-wide
test transaction guard, non-APT dependency previews, installed grid mode, optional
toast/background notifications, full source editing and user correction of app
grouping, validated AppImage update metadata, accent following and additional
language contribution infrastructure. Snapshot integration and community/release
publication also remain open. Every item retains its own note in the roadmap.

Do not replace these requirements with unit-test counts, static metadata or an
old screenshot ZIP. Real transactions require a disposable environment and the
explicit package/operation authorization described in the acceptance plan.
