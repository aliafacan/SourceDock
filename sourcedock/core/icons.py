"""Read-only icon path discovery for installed and store applications."""

from pathlib import Path
import re


def _candidate_names(app_id: str) -> tuple[str, ...]:
    value = (app_id or "").strip()
    if not value or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value):
        return ()
    names = [value]
    if not value.endswith(".desktop"):
        names.append(f"{value}.desktop")
    return tuple(dict.fromkeys(names))


def find_flatpak_icon_path(app_id: str, remote: str = "", roots=None) -> str:
    """Find a real Flatpak icon without invoking Flatpak or changing state."""
    names = _candidate_names(app_id)
    if not names or (remote and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", remote)):
        return ""

    flatpak_roots = tuple(Path(root) for root in roots) if roots is not None else (
        Path("/var/lib/flatpak"),
        Path.home() / ".local/share/flatpak",
    )
    exported_roots = tuple(root / "exports/share/icons/hicolor" for root in flatpak_roots)
    size_names = ("128x128", "64x64", "48x48", "32x32", "scalable")
    extensions = ("png", "svg")

    for root in exported_roots:
        for size_name in size_names:
            for name in names:
                for extension in extensions:
                    path = root / size_name / "apps" / f"{name}.{extension}"
                    if path.is_file():
                        return str(path)

    remotes = (remote,) if remote else ("flathub",)
    architectures = ("x86_64", "aarch64", "arm", "i386")
    appstream_roots = tuple(root / "appstream" for root in flatpak_roots)
    for appstream_root in appstream_roots:
        for remote_name in remotes:
            for architecture in architectures:
                root = appstream_root / remote_name / architecture
                # Resolve the metadata generation once, not once per size/name.
                icon_roots = sorted(root.glob("*/icons"))
                for size_name in size_names[:-1]:
                    for name in names:
                        for extension in extensions:
                            for icon_root in icon_roots:
                                path = icon_root / size_name / f"{name}.{extension}"
                                if path.is_file():
                                    return str(path)

    app_roots = tuple(root / "app" for root in flatpak_roots)
    for app_root in app_roots:
        for architecture in architectures:
            for name in names:
                pattern = f"{app_id}/{architecture}/*/files/share/icons/hicolor/*/apps/{name}.*"
                for path in sorted(app_root.glob(pattern)):
                    if path.is_file() and path.suffix.casefold() in {".png", ".svg"}:
                        return str(path)
    return ""


def find_snap_icon_path(snap_name: str, roots=None) -> str:
    """Find a Snap's own icon without asking the store or changing state."""
    value = (snap_name or "").strip()
    if not value or Path(value).name != value:
        return ""
    snap_roots = tuple(Path(root) for root in roots) if roots is not None else (
        Path("/snap"),
        Path("/var/lib/snapd/snap"),
    )
    for root in snap_roots:
        for extension in ("png", "svg"):
            path = root / value / "current/meta/gui" / f"icon.{extension}"
            if path.is_file():
                return str(path)
    return ""
