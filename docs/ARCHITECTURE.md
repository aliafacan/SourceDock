# Architecture

`main.py` routes normal startup, details, updates, uninstall and standalone package previews.
`sourcedock/constants.py` is the version source. GTK 3 and PyGObject remain the UI foundation.

| Layer | Responsibility |
| --- | --- |
| `core/models.py` | Typed application, package, store and installation data |
| `core/runner.py`, `core/process.py` | Command execution, deadlines, redaction, credentials and operation serialization |
| `core/json_store.py`, `core/history.py`, `core/app_lists.py` | Atomic state, redacted history and restoration planning |
| `backend/*` | Native providers, Flatpak/Snap/firmware, scanner and local packages |
| `backend/archive_safety.py`, `portable.py` | Bounded extraction and ownership-constrained removal |
| `backend/updates.py`, `previews.py`, `sources.py` | Update catalog, read-only package plans and configured sources |
| `store/registry.py`, `store/metadata.py` | Catalog searches and optional AppStream declarations |
| `ui/window.py` | Assemble pages, theme and shared application state |
| `ui/views/shell_view.py` | Persistent navigation, compact sidebar and global search |
| `ui/views/*` | Installed, discovery, packages, updates, operations, settings and advanced dialogs |
| `ui/components/*` | Common states, cards, screenshot galleries, details, progress and mini installer |

The existing notebook is retained as an internal page container with hidden tabs;
provider APIs do not depend on navigation. Data and package work run in workers;
GTK updates are marshalled with GLib.idle_add. The standalone installer does not build
or load the main store window.

Identity is explicit: source plus package ID, or an available AppStream ID. Display
names and substring matches do not establish equivalence. Unknown metadata is omitted.

Package and firmware cancellation is restricted. External system processes can be
observed but are not signalled. Native privileged operations are serialized; the
system package manager remains responsible for its own database locks.
