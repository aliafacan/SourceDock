"""Conservative application identities shared by store cards and migrations."""

from pathlib import Path
import re

from sourcedock.core.models import NATIVE_SOURCES, SOURCE_FLATPAK, SOURCE_SNAP, is_native_source

SWITCHABLE_SOURCES = NATIVE_SOURCES | {SOURCE_FLATPAK, SOURCE_SNAP}

# Channels and similarly named products deliberately have separate identities.
_ALIASES = {
    "google-chrome": "com.google.chrome",
    "google-chrome-stable": "com.google.chrome",
    "firefox": "org.mozilla.firefox",
    "chromium": "org.chromium.chromium",
    "chromium-browser": "org.chromium.chromium",
    "vlc": "org.videolan.vlc",
    "gimp": "org.gimp.gimp",
    "inkscape": "org.inkscape.inkscape",
    "obs-studio": "com.obsproject.studio",
    "telegram-desktop": "org.telegram.desktop",
}


def canonical_identity(value):
    value = value.casefold().removesuffix(".desktop")
    value = re.sub(r"[^a-z0-9.+:_-]+", "", value)
    return _ALIASES.get(value, value)


def store_identity(result):
    package = canonical_identity(result.app_id)
    known = set(_ALIASES.values())
    if package in known or package.startswith(("google-chrome-", "com.google.chrome.")):
        return package
    return canonical_identity(result.identity or result.app_id)


def installation_key(application):
    package = application.package_name or application.id
    if is_native_source(application.source):
        package = package.split(":", 1)[0]
    return (application.source, package,
            application.install_path if application.source == SOURCE_FLATPAK else "")


def matching_installations(result, applications, variants=()):
    """Use package/AppStream/desktop IDs; display names alone never authorize removal."""
    if not result.is_application or result.source not in SWITCHABLE_SOURCES:
        return []
    identity = store_identity(result)
    if not identity:
        return []
    linked_packages = {
        (variant.source, variant.app_id)
        for variant in (*variants, result)
        if variant.is_application and store_identity(variant) == identity
    }
    found = {}
    for application in applications:
        if application.source not in SWITCHABLE_SOURCES or not application.desktop_file:
            continue
        package = installation_key(application)[1]
        keys = {canonical_identity(package), canonical_identity(Path(application.desktop_file).name)}
        if identity in keys or (application.source, package) in linked_packages:
            found.setdefault(installation_key(application), application)
    return list(found.values())
