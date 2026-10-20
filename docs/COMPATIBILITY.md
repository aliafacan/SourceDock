# Compatibility

Evidence date: 2026-10-20. "Tested" refers only to the workflows explicitly listed.
It distinguishes clearly between unit tests using mocked runners, CI automated pipelines, and verified real host transactions.

| Environment | Status | Evidence | Remaining |
| --- | --- | --- | --- |
| **Zorin OS 18.1** (GNOME 46, Python 3.12, GTK 3) | **Tested: Real Host Package Lifecycle** | Clean 1.3.0 `.deb` installation, live desktop startup, real APT `sl` package install/remove cycle verified in `dpkg.log` and `history.json`. | Full long-term stress testing; complex multi-dependency upgrades |
| **Zorin OS 17.x** | **Untested on Real Hardware** | Shares Ubuntu 22.04 base; covered by automated CI test suite. | Real hardware installation verification |
| **Ubuntu 22.04 & 24.04** | **CI PASS** | GitHub Actions CI: 281/281 tests passed under Xvfb + Openbox, Ruff clean, compileall clean, `.deb` build verified. | Disposable VM acceptance for real un-mocked package transactions |
| **Debian 12 (Bookworm)** | **Compatible (`.deb`)** | Shares APT backend and Python 3.11 / GTK 3 dependencies. | Clean installation and package transaction testing |
| **Debian 11 (Bullseye)** | **Unsupported Out-of-the-Box** | Ships with Python 3.9 by default; SourceDock strictly requires Python >= 3.10. | Upgrade Python / system |
| **Fedora / openSUSE / Arch** | **Experimental** | DNF, Zypper, and Pacman parsers and interfaces implemented; validated via mocked unit test suites. | Real-world startup, native packaging (.rpm / PKGBUILD), and live privileged testing |
## Architecture & Packaging Notes

- `Architecture: all` applies to the Python application code. Target systems must provide required runtime dependencies: Python 3.10+, PyGObject (`python3-gi`, `python3-gi-cairo`), and GTK 3 (`gir1.2-gtk-3.0`, `gir1.2-gdkpixbuf-2.0`).
- The `.deb` package is specifically built for Debian and Ubuntu-derived distributions. It is not an RPM, PKGBUILD, or universal binary.

## Integrations & Optional Components

- **Flatpak, Snap, and fwupd**: Strictly optional. If these tools are not installed on the system, SourceDock cleanly marks them as unavailable without errors or unsolicited background service installation.
- **GNOME Shell Extension**: The desktop right-click menu extension (`sourcedock-menu@aliafacan.dev`) targets modern GNOME Shell (46+) AppMenu APIs. Older releases (e.g. GNOME 42/43) use legacy extension interfaces and require separate validation.
- **Hardware Firmware**: Firmware queries use `fwupd` read-only interfaces. Live hardware firmware writing is never performed automatically.
