"""Build an update catalog from measured provider data, without fuzzy identity."""

from dataclasses import dataclass

from sourcedock.core.models import (
    SOURCE_FIRMWARE,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    UnifiedApplication,
    is_native_source,
)


@dataclass(frozen=True)
class UpdateItem:
    application: UnifiedApplication
    group: str
    new_version: str = ""


def build_update_catalog(applications, packages, native_source):
    items = []
    native_apps = set()
    package_versions = {package.name: package.new_version for package in packages}
    seen = set()
    for app in applications:
        if is_native_source(app.source):
            native_apps.add(app.package_name)
        if not app.update_available:
            continue
        identity = (app.source, app.package_name or app.id, app.install_path)
        if identity in seen:
            continue
        seen.add(identity)
        group = "applications"
        if app.source == SOURCE_FIRMWARE:
            group = "firmware"
        elif (
            app.source in (SOURCE_FLATPAK, SOURCE_SNAP) and not app.desktop_file and app.category == "System"
        ):
            group = "runtimes"
        new_version = (
            package_versions.get(app.package_name, "")
            if is_native_source(app.source)
            else app.update_note.removeprefix("-> ")
        )
        items.append(UpdateItem(app, group, new_version))
    for package in packages:
        if package.update_available and package.name not in native_apps:
            app = UnifiedApplication(
                id=f"{native_source}:{package.name}",
                name=package.name,
                source=native_source,
                version=package.version,
                package_name=package.name,
                update_available=True,
                installed_size_kib=package.installed_size_kib,
                update_note=package.new_version,
            )
            items.append(UpdateItem(app, "system", package.new_version))
    return sorted(items, key=lambda item: (item.group, item.application.name.casefold()))
