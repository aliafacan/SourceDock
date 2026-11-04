# Authorization and Cancellation

The active implementation uses sudo when available and supports a sudo-less
root-login system only when the already-running process has UID 0. It never
elevates an unprivileged process and never launches the GTK application as root
as an authorization workaround. Privileged commands use argv lists and stdin
authentication; passwords are cleared when the operation finishes or fails.
Streaming diagnostics mask secrets and home paths. A shared lock serializes
privileged operations.

Critical commands cannot be cancelled from the UI. Subprocess deadlines use a
nonblocking selector, so silence does not disable the timeout. Safe cancellation
terminates the process group, with a bounded fallback for a child ignoring SIGTERM.
The operation result is reported only after the worker exits.

## Selected updates in 1.4.10

Selected native updates are grouped by provider. APT uses one
`apt-get -o DPkg::Lock::Timeout=0 install --only-upgrade -y -- ...` command,
with exact Debian package names validated before privileged execution. Shell
syntax, options, paths and version expressions are rejected as package names;
architecture-qualified names are retained. Password lifetime and critical-process
cancellation rules remain unchanged.

Flatpak selections retain their installation paths so the user and system copies
of an application are separate targets. Update completion, including failure,
clears the busy state before refreshing the visible update list. Provider errors
remain visible rather than being converted to a successful result.

Installation and update completion reconcile installed metadata in the background
with update discovery disabled for native packages, Flatpak, Snap and firmware.
The current page, filters and unrelated checked updates remain visible. Known
successful update targets are removed from the update catalog; failed providers
retain their last visible data. Explicit refresh/check actions still discover
updates. Confirmed removals are applied directly to the current lists.

Internal sudo probes and password validation capture diagnostics without streaming
them to operation windows. Their actual failure status is still checked. Real
package-manager output remains visible and redacted. A silent command displays a
running phase and elapsed time; percentages are shown only when supplied by the
provider, never estimated from elapsed time.

Before a release, verify five and fifteen selected APT updates in isolated Debian
Trixie and Forky VMs, including an expired sudo session, an external dpkg lock,
partial package failure and a transaction continuing past its UI deadline. Compare
the final dpkg state and remaining updates with the UI. Unit tests use fake runners;
they do not establish behavior on those distributions.

### Credential Lifecycle and Authorization Isolation

- **Centralized Session Auth**: Sudo passwords are held in a single session
  context on the main application window and are never duplicated across views or dialogs.
- **Strict 15-minute TTL**: In-memory credentials expire automatically after 15 minutes,
  aligning with the default Linux sudo timestamp cache (`timestamp_timeout`).
- **Immediate Invalidation**: The cached credential is immediately cleared upon:
  1. An authentication failure (`AuthRequiredError` with `password_failed=True`).
  2. User cancellation of an authentication or operation dialog.
  3. Main window destruction / session termination (`destroy` event).
- **Redaction Guard**: All streaming command output, exceptions, and diagnostics
  actively redact secrets and user home paths via `redact_text()`.
- **Command Authentication**: After isolated validation, a supplied password is
  passed to the actual privileged command only through sudo stdin (`sudo -k -S`);
  it is never included in argv or operation logs. This avoids relying on a
  sudo timestamp cache that may not be shared between subprocess contexts.
- **Cancellation Boundary**: Active mutating package transactions (APT, dpkg, DNF,
  RPM, Pacman, Zypper, Snap, fwupdmgr) are marked critical (`critical_command()`);
  invoking UI cancellation on these operations returns `False` and leaves the
  underlying process group intact to prevent filesystem lock and transaction corruption.
  Safe phases, such as waiting for APT locks (`_wait_for_apt_locks`) or read-only provider
  queries, support immediate, responsive cancellation.

## Polkit Migration Proposal

An installed helper should expose a fixed operation enum, validate package IDs and
local paths, and call only the corresponding provider command. The policy must name
that helper, not permit arbitrary shell execution. GUI code remains unprivileged.

Read-only proof of the simulation boundary:

```bash
apt-get --simulate -o Debug::NoLocking=true install -- ./packaging/sourcedock_1.4.8_all.deb
```

`backend/previews.py` implements that command and tests assert that it never calls
sudo or run_privileged. A production Polkit policy/helper is deliberately not
installed until its authorization boundary has separate review and distribution tests.

### Proof-of-concept artifacts (not shipped)

The review now includes a small, auditable PoC under `packaging/polkit/`:

- `dev.aliafacan.sourcedock.policy` names exactly one action
  (`dev.aliafacan.sourcedock.manage-local-packages`), binds it to the fixed helper
  path and sets `allow_any`/`allow_inactive` to `no`.
- `sourcedock-helper` exposes a fixed operation enum (`install-local`,
  `remove-package`), validates package IDs and staged paths, refuses symlinks and
  paths outside `/var/cache/sourcedock/`, and runs the native manager through an
  argv list. It never uses a shell and never re-executes sudo.

`packaging/build_deb.sh` intentionally does **not** install either file, so the
active `1.4.8` behavior remains limited to the reviewed sudo/direct-root paths.
`tests/test_polkit_helper.py` pins the
security properties. Enabling this path still requires an independent review, a
D-Bus-activated variant for the custom action, and per-distribution acceptance;
that part remains open.
