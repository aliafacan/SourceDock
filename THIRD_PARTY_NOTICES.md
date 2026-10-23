# Third-Party Notices

SourceDock project copyright: (C) 2026 Ali Afacan <aliafacan.dev@gmail.com>.
SourceDock source is distributed under GPL-3.0-only; the complete, unmodified text
is in LICENSE. The Free Software Foundation notice in that document identifies
the license text's copyright, not the SourceDock project's authorship.

- The SourceDock source-and-dock SVG is a project asset. PNG sizes are rendered from that SVG.
- GTK, PyGObject, GdkPixbuf and GLib are system dependencies with their own upstream licenses.
- Adwaita/symbolic icons are loaded from the installed system theme; icon artwork is not copied into the source tree.
- Provider application icons and screenshots remain their respective projects' artwork and are displayed from available metadata.
- AppStream metadata added by this project declares CC0-1.0 for the metadata document.
- GPL-3 text matches the canonical system common-license document; project copyright belongs in source/package attribution, not in a modified license text.

Ruff is a development tool and is not bundled into the application package.

## Runtime dependency inventory

SourceDock bundles no third-party code. It imports system libraries and calls
system tools. The table below records what each dependency is used for, whether
it is required or optional, and its upstream license family. The licenses belong
to the upstream projects and are not relicensed by SourceDock.

| Component | Required | Used for | Upstream license |
| --- | --- | --- | --- |
| Python 3 (>= 3.10) | Yes | Runtime interpreter | PSF-2.0 |
| PyGObject (`python3-gi`) | Yes | GTK bindings | LGPL-2.1-or-later |
| GTK 3 (`gir1.2-gtk-3.0`) | Yes | Desktop UI toolkit | LGPL-2.1-or-later |
| GLib/GIO | Yes | Main loop, GSettings | LGPL-2.1-or-later |
| GdkPixbuf (`gir1.2-gdkpixbuf-2.0`) | Yes | Icon/bitmap loading | LGPL-2.1-or-later |
| Adwaita icon theme | Yes (desktop) | Symbolic icons | LGPL-3.0-or-later / CC-BY-SA-3.0 |
| APT / DPKG | Debian family | Native package provider | GPL-2.0-or-later |
| DNF / RPM | Fedora family (optional) | Native package provider | GPL-2.0-or-later / LGPL-2.1 |
| Pacman | Arch family (optional) | Native package provider | GPL-2.0-or-later |
| Zypper / libzypp | openSUSE family (optional) | Native package provider | GPL-2.0-or-later |
| Flatpak (+ `gir1.2-flatpak-1.0`) | Optional | Flatpak provider | LGPL-2.1-or-later |
| Snapd | Optional | Snap provider | GPL-3.0-only |
| fwupd | Optional | Firmware updates | LGPL-2.1-or-later |
| GNOME Shell | Optional | Right-click integration host | GPL-2.0-or-later |
| Ruff | Dev/test only | Lint and security scan | MIT |

System libraries and tools are invoked as separate programs or imported from the
distribution; SourceDock does not redistribute them.

The Debian package includes project attribution and the full GPL text in
`/usr/share/doc/sourcedock/copyright`, a separate unmodified `LICENSE`, and this
`THIRD_PARTY_NOTICES.md` file. This inventory reflects the imported modules and
invoked tools at source-version 1.4.0; it is a maintained summary, not a legal
audit, and does not cover the artwork of applications displayed by the store.
