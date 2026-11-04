"""Cheap change detection for the persisted installed-application inventory."""

import hashlib
import os
from pathlib import Path

from sourcedock.core.models import DESKTOP_DIRS


def inventory_fingerprint():
    """Stat package databases and deployment pointers, never application payloads."""
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    roots = [(Path(path), 1) for path in DESKTOP_DIRS]
    roots += [(data / "applications", 1), (data / "sourcedock/portable_registry.json", 0)]
    roots += [(Path(path), depth) for path, depth in (
        ("/var/lib/dpkg/status", 0), ("/var/lib/rpm", 1),
        ("/usr/lib/sysimage/rpm", 1), ("/var/lib/pacman/local", 1),
        ("/var/lib/snapd/sequence", 1), ("/var/lib/snapd/desktop/applications", 1),
    )]
    for base in (Path("/var/lib/flatpak"), data / "flatpak"):
        # app/id/arch/branch/active and runtime/id/arch/branch/active.
        roots.extend((base / name, 4) for name in ("app", "runtime"))
    roots.extend((home / name, 3) for name in ("Applications", "AppImages", "Downloads"))
    digest = hashlib.sha256()

    def visit(path, depth):
        try:
            stat = path.lstat()
            digest.update(str((str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)).encode())
            if depth and path.is_dir() and not path.is_symlink():
                for child in sorted(path.iterdir()):
                    visit(child, depth - 1)
        except FileNotFoundError:
            digest.update(str((str(path), "missing")).encode())

    try:
        for path, depth in roots:
            visit(path, depth)
    except OSError:
        return None  # An unreadable database must never validate a stale cache.
    return digest.hexdigest()
