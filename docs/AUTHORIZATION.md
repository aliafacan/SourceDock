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
