# Troubleshooting

## APT says the package is already current

Building a .deb with the installed version does not force an upgrade. Use a newer
version or `sudo apt install --reinstall ./packaging/sourcedock_<version>_all.deb`.

## SourceDock does not open

Run `sourcedock` from a terminal and include the traceback in an issue. The test suite
now constructs the complete main window, rather than testing only its helper methods.
Check Python 3.10+, GTK 3 and python3-gi availability. `sourcedock --version` prints the version.

If launched from a Snap-hosted editor, GTK/module environment variables may refer to
Snap libraries. `main.py` cleans that environment before startup. For test commands,
use the system interpreter and a clean GTK environment.

## Right-click actions are missing

The GNOME extension must be enabled in the desktop session:

```bash
gnome-extensions info sourcedock-menu@aliafacan.dev
gnome-extensions enable sourcedock-menu@aliafacan.dev
```

Log out and back in after installing/updating an extension. A copy in
`~/.local/share/gnome-shell/extensions/sourcedock-menu@aliafacan.dev` overrides the system
copy installed by APT. Refresh that user copy with the packaged source/extension ZIP.
The current Zorin app context menu inherits GNOME's AppMenu, which is the integration point.

## Portable removal is refused

Do not add an ownership file to an arbitrary folder. Legacy or modified records are
visible, but automatic deletion requires a matching manifest, registry identity and
managed root. Existing personal folders are not treated as disposable installations.
Legacy apps need a new managed installation or manual folder management; their data
is not silently deleted or reclassified as owned.

## Archives containing links are rejected

The current extractor rejects symlinks, hard links and special files, and limits
member count, per-file size, total extracted size and ZIP compression ratio. Some
otherwise legitimate vendor archives need a link-free distribution. A failed archive
upgrade preserves the existing executable and shortcut.

## An operation cannot be cancelled

Native package and firmware transactions must finish. Closing an installer is blocked
while it is working. External APT/DPKG entries are informational; SourceDock does not
pause or terminate other programs' package processes.

## Restore cannot install an entry

Already-installed entries are excluded. Native entries require a matching distribution
and manager. Flatpak entries need an explicit remote and use user scope. Portable and
AppImage entries need their original local files. Recorded versions are informational,
not a promise that old repository versions are available. Snap classic applications
may require individual installation and explicit confinement approval.

## Installation methods

Use APT to manage .deb installations. `install.sh` refuses to overwrite package-owned
files. The manual uninstaller requires a manual-install marker; if APT owns SourceDock it
delegates removal to APT. User preferences, history and portable apps are not removed
with the program package.
