"""Versioned application exports and conservative restoration planning."""

from dataclasses import dataclass
import json
import re

from sourcedock.core.errors import BackendError
from sourcedock.core.models import NATIVE_SOURCES, SOURCE_FLATPAK, SOURCE_SNAP


@dataclass(frozen=True)
class RestoreItem:
    name: str
    source: str
    package: str
    version: str
    origin: str = ""
    reason: str = ""

    @property
    def eligible(self):
        return not self.reason


def export_applications(applications, distro):
    return json.dumps(
        {
            "schema": 1,
            "distro": distro.id,
            "native_manager": distro.native_manager,
            "applications": [
                {
                    "name": app.name,
                    "source": app.source,
                    "package": app.package_name,
                    "version": app.version,
                    "origin": app.origin,
                }
                for app in applications
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def plan_restore(data, distro, installed):
    records = data.get("applications") if isinstance(data, dict) else data
    if not isinstance(records, list) or len(records) > 2000:
        raise BackendError("Invalid or oversized application list.")
    if isinstance(data, dict) and data.get("schema") != 1:
        raise BackendError("Unsupported application list schema.")
    same_distro = (
        isinstance(data, dict)
        and data.get("distro") == distro.id
        and data.get("native_manager") == distro.native_manager
    )
    known = {(app.source, app.package_name) for app in installed}
    plan = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or any(
            not isinstance(record.get(key, ""), str)
            for key in ("name", "source", "package", "version", "origin")
        ):
            raise BackendError("Invalid application record.")
        package = record.get("package", "")
        source = record.get("source", "")
        if source in NATIVE_SOURCES | {SOURCE_FLATPAK, SOURCE_SNAP} and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9+_.:@-]{0,255}", package
        ):
            raise BackendError("Invalid package identifier in application list.")
        identity = (source, package)
        if identity in seen:
            continue
        seen.add(identity)
        origin = record.get("origin", "")
        reason = ""
        if identity in known:
            reason = "restore_already_installed"
        elif source in NATIVE_SOURCES and (source != distro.native_manager or not same_distro):
            reason = "restore_distro_mismatch"
        elif source == SOURCE_FLATPAK and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", origin):
            reason = "restore_remote_missing"
        elif source not in NATIVE_SOURCES | {SOURCE_FLATPAK, SOURCE_SNAP}:
            reason = "restore_local_file"
        plan.append(
            RestoreItem(
                record.get("name") or package, source, package, record.get("version", ""), origin, reason
            )
        )
    return plan


def install_restore_item(registry, item):
    if not item.eligible:
        raise BackendError("This restoration target is not eligible.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.:@-]{0,255}", item.package):
        raise BackendError("Invalid restoration package identifier.")
    if item.source in NATIVE_SOURCES:
        registry.runner.run_privileged(
            registry.get_native_provider(item.source).install_command(item.package)
        )
    elif item.source == SOURCE_FLATPAK:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", item.origin):
            raise BackendError("Invalid restoration remote identifier.")
        registry.runner.run(
            ["flatpak", "install", "--user", "--noninteractive", "-y", item.origin, item.package],
            timeout=1800,
            check=True,
        )
    elif item.source == SOURCE_SNAP:
        registry.runner.run_privileged(["snap", "install", item.package])
    else:
        raise BackendError("Unsupported restoration source.")
