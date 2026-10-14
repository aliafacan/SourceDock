# Compatibility

Evidence date: 2026-10-14. "Tested" refers only to the workflows explicitly listed.
It does not imply that real privileged installation/removal was performed.

| Environment | Status | Evidence | Remaining |
| --- | --- | --- | --- |
| Zorin OS 18.1, GNOME 46, Python 3.12, GTK 3 | Tested: UI/read-only flows | Actual application/package catalog; startup; TR/EN; dark/light; UI screenshots; SourceDock 1.3.0 .deb build and APT simulation | Clean install/uninstall of 1.3.0, actual provider transactions, enabled extension click test |
| Ubuntu 22.04/24.04 | CI configured, not independently tested | Workflow uses each runner's system Python and GI | Remote CI execution and clean VM acceptance |
| Debian with Python 3.10+ and GTK 3 | Not tested | Native backend interfaces and .deb metadata | Clean VM workflows |
| Fedora / openSUSE / Arch | Experimental | DNF/Zypper/Pacman command/parsing tests use fake runners | Actual startup, package transactions and native packaging |
| Python below 3.10 | Unsupported | Package dependency and code syntax | Upgrade Python/system |

`Architecture: all` applies to the Python application code. Runtime dependencies
still need to exist for the target architecture; the .deb is for Debian-family
systems. It is not an RPM, PKGBUILD or universal Linux binary.

The GNOME extension uses the GNOME Shell ESM/AppMenu API. GNOME 42/43 do not use the
same extension entry point. Its advertised newer shell versions require separate
runtime validation; shipping metadata is not proof of compatibility.

Flatpak, Snap and firmware tools are optional. Missing tools produce empty or
unavailable-source states. No automatic daemon installation or repository editing
is performed merely by opening the application.
