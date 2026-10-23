# Test Layers

The supported entry point is `python3 tools/run_tests.py`. It discovers tests
after installing a process-wide Python audit hook, isolates XDG data/config/cache
and temporary files, and fails the run if an unexpected real command is attempted,
even when application code catches the exception. Package managers, privilege
helpers, host bridges, shell commands and unknown executables are blocked.

The narrow exceptions are `.deb` metadata inspection, `dpkg --compare-versions`,
the read-only X11 WM probe, desktop-cache updates within the owned temporary root,
and Python fixture subprocesses. This is an accident guard for trusted tests,
not an OS security sandbox: Python child scripts/native libraries are not confined.
Real transaction acceptance still requires a disposable VM. Raw
`python3 -m unittest ...` does not enable this guard and is not the CI entry point.

## Backend And Security

```bash
python3 tools/run_tests.py tests.test_safety tests.test_provider_timeouts \
  tests.test_stage5 tests.test_flatpak_cleanup tests.test_app_lists tests.test_host_guard
```

`test_safety` uses disposable subprocesses and temporary archive/registry files.
Provider command and parsing tests use fake runners. Cleanup tests verify exact
references, scopes, cancellation and stale-plan rejection.

## GTK Workflows

```bash
xvfb-run -a -s '-screen 0 1366x768x24' bash -c '
  openbox >/tmp/sourcedock-test-wm.log 2>&1 & wm=$!
  trap "kill $wm 2>/dev/null || true" EXIT
  /usr/bin/python3 tools/run_tests.py --require-wm
'
```

Run with the system Python that provides PyGObject. Remove inherited Snap GTK,
GdkPixbuf, GIO and library environment variables first. Use temporary
`XDG_DATA_HOME`, `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` for test-owned data.
Window-manager geometry tests require an isolated Openbox session; without it
they explicitly skip and must not be reported as passed.

To inspect a freshly built package instead of an older tracked artifact:

```bash
bash packaging/build_deb.sh /tmp/sourcedock-test-package
export SOURCEDOCK_TEST_DEB=/tmp/sourcedock-test-package/sourcedock_1.4.0_all.deb
# Then run the Xvfb/Openbox command above.
```

CI builds before running tests and supplies this exact artifact path. A missing
explicit package is a failure; it does not silently fall back to another file.
CI installs Openbox on its disposable runner and requires WM readiness, so geometry
tests no longer silently skip merely because Xvfb has no window manager.

## UI Performance

`tools/ui_performance.py --output /tmp/unique-result.json --scale 100` measures
1,000 synthetic installed rows, actual header search, source/category filters and
scroll-to-last-row through the production GTK controls. Run it inside an isolated
Xvfb/Openbox session as above. Repeat with roots `1024x768` and `1366x768`, and
`--scale 125`. No real providers are queried, no screenshot showcase is generated,
and existing result files are never overwritten. Initial model setup and warmup
are reported separately from five measured iterations.

The result separates synchronous handler time from the first GTK draw of the
expected state. P95 budgets are 1,000 ms population, 350 ms search (including GTK's
local SearchEntry delay), 250 ms filters, 50 ms programmatic scrolling. These are
software-X11 responsiveness targets, not GPU FPS, hardware wheel latency, network
search or a claim about all real 1,000-app catalogs. A timeout or exceeded budget
is FAIL, not a successful sample.

## Physical X11 Acceptance

```bash
SOURCEDOCK_TEST_PACKAGE=/tmp/sourcedock-test-package/sourcedock_1.4.0_all.deb \
  bash tools/run_acceptance_x11.sh
```

The runner creates its own Xvfb roots and Openbox process groups, validates root
pixels, workareas, outer frames, fixed controls and unadjusted dialog geometry,
and cleans up its own processes. Existing evidence directories are not overwritten.
Provider timeouts remain in `validation.json`; geometry success does not imply
that every provider returned a complete catalog.

## Real Transactions

Use disposable VMs and the scenarios in
`docs/RELEASE_ACCEPTANCE_ENVIRONMENT.md`. Test commands, package names and
expected side effects must be reviewed for that VM. GNOME Shell integration
requires an actual GNOME session. Unit tests, fake commands, static metadata,
root screenshots and container inspection are not substitutes for these tests.
