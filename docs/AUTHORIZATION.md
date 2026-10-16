# Authorization and Cancellation

The active implementation retains sudo for compatibility. It never launches the
GTK application as root. Privileged commands use argv lists and stdin authentication;
passwords are cleared when the operation finishes or fails. Streaming diagnostics
mask secrets and home paths. A shared lock serializes privileged operations.

Critical commands cannot be cancelled from the UI. Subprocess deadlines use a
nonblocking selector, so silence does not disable the timeout. Safe cancellation
terminates the process group, with a bounded fallback for a child ignoring SIGTERM.
The operation result is reported only after the worker exits.

## Polkit Migration Proposal

An installed helper should expose a fixed operation enum, validate package IDs and
local paths, and call only the corresponding provider command. The policy must name
that helper, not permit arbitrary shell execution. GUI code remains unprivileged.

Read-only proof of the simulation boundary:

```bash
apt-get --simulate -o Debug::NoLocking=true install -- ./packaging/sourcedock_1.3.0_all.deb
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
active `1.3.0` behavior is unchanged. `tests/test_polkit_helper.py` pins the
security properties. Enabling this path still requires an independent review, a
D-Bus-activated variant for the custom action, and per-distribution acceptance;
that part remains open.

