# Authorization and Cancellation

The active implementation retains sudo for compatibility. It never launches the
GTK application as root. Privileged commands use argv lists and stdin authentication;
passwords are cleared when the operation finishes or fails. Streaming diagnostics
mask secrets and home paths. A shared lock serializes privileged operations.

Critical commands cannot be cancelled from the UI. Subprocess deadlines use a
nonblocking selector, so silence does not disable the timeout. Safe cancellation
terminates the process group, with a bounded fallback for a child ignoring SIGTERM.
The operation result is reported only after the worker exits.

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
apt-get --simulate -o Debug::NoLocking=true install -- ./packaging/sourcedock_1.4.1_all.deb
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
active `1.4.1` behavior is unchanged. `tests/test_polkit_helper.py` pins the
security properties. Enabling this path still requires an independent review, a
D-Bus-activated variant for the custom action, and per-distribution acceptance;
that part remains open.

