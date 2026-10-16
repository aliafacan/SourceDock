#!/usr/bin/env python3
"""Taşınabilir (Portable / Archive) uygulamalar sağlayıcısı ve kayıt yöneticisi."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import uuid

from sourcedock.core.errors import BackendError
from sourcedock.core.json_store import write_json
from sourcedock.core.models import SOURCE_PORTABLE, UnifiedApplication
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.scanner import _clean_exec_command, _normalize_path


def _get_portable_registry_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    base = data_home / "sourcedock"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base / "portable_registry.json"


def _get_legacy_portable_registry_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "voltapp" / "portable_registry.json"


def load_portable_registry() -> dict[str, dict]:
    for path in (_get_portable_registry_path(), _get_legacy_portable_registry_path()):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def save_portable_registry(registry: dict[str, dict]) -> None:
    path = _get_portable_registry_path()
    try:
        write_json(path, registry)
    except OSError as exc:
        raise BackendError(f"Portable registry could not be saved: {exc}") from exc


MANIFEST_NAME = ".sourcedock-managed.json"
LEGACY_MANIFEST_NAME = ".voltapp-managed.json"


def validate_portable_path(path: Path, item: dict, app_id: str) -> None:
    root = Path(item.get("managed_root", ""))
    if not item.get("managed_root") or not item.get("ownership_token"):
        raise BackendError("Portable ownership is unverified. Reinstall with SourceDock before removing it.")
    if (
        ".." in path.parts
        or path.is_symlink()
        or root.is_symlink()
        or path.parent.resolve() != root.resolve()
    ):
        raise BackendError("Unsafe portable installation path.")
    if path.resolve() == root.resolve() or path.resolve() == Path.home().resolve():
        raise BackendError("Unsafe portable installation path.")
    manifest_path = next(
        (path / name for name in (MANIFEST_NAME, LEGACY_MANIFEST_NAME) if (path / name).exists()), None
    )
    if manifest_path is None or manifest_path.is_symlink():
        raise BackendError("Portable ownership manifest is missing or invalid.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError("Portable ownership manifest is missing or invalid.") from exc
    if not isinstance(manifest, dict):
        raise BackendError("Portable ownership manifest is invalid.")
    for key, value in (
        ("id", app_id),
        ("install_path", str(path.resolve())),
        ("managed_root", str(root.resolve())),
        ("ownership_token", item["ownership_token"]),
        ("desktop_file", item.get("desktop_file", "")),
    ):
        if manifest.get(key) != value:
            raise BackendError("Portable ownership manifest does not match the registry.")


def register_portable_app(
    name: str,
    version: str,
    install_path: str,
    executable: str,
    desktop_file: str,
    icon: str = "",
    size_kib: int | None = None,
    managed_root: str | None = None,
) -> None:
    reg = load_portable_registry()
    app_id = f"{SOURCE_PORTABLE}:{name.lower().replace(' ', '_')}"
    today = datetime.now().strftime("%Y-%m-%d")
    path = Path(install_path)
    root = Path(managed_root) if managed_root else _get_portable_registry_path().parent / "apps"
    if path.is_symlink() or root.is_symlink() or path.parent.resolve() != root.resolve() or not path.is_dir():
        raise BackendError("Unsafe portable registration path.")
    token = uuid.uuid4().hex
    reg[app_id] = {
        "id": app_id,
        "name": name,
        "version": version,
        "install_path": install_path,
        "executable": executable,
        "desktop_file": desktop_file,
        "icon": icon or "application-x-executable",
        "size_kib": size_kib,
        "installed_date": today,
        "last_updated": today,
        "managed_root": str(root.resolve()),
        "ownership_token": token,
    }
    manifest = dict(reg[app_id], install_path=str(path.resolve()))
    (path / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    save_portable_registry(reg)


def unregister_portable_app(app_id: str) -> None:
    reg = load_portable_registry()
    if app_id in reg:
        del reg[app_id]
        save_portable_registry(reg)


class PortableProvider:
    """Taşınabilir (.tar.gz, .zip vb.) arşivlerden kurulan uygulamaları yöneten sağlayıcı."""

    source = SOURCE_PORTABLE

    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def list_applications(self) -> list[UnifiedApplication]:
        reg = load_portable_registry()
        apps: list[UnifiedApplication] = []
        changed = False

        for app_id, item in list(reg.items()):
            if not isinstance(item, dict):
                continue
            if any(
                not isinstance(item.get(key, ""), str)
                for key in (
                    "name",
                    "version",
                    "install_path",
                    "executable",
                    "desktop_file",
                    "icon",
                    "installed_date",
                    "last_updated",
                )
            ):
                continue
            install_path = item.get("install_path", "")
            executable = item.get("executable", "")
            desktop_file = item.get("desktop_file", "")

            size_kib = item.get("size_kib")
            if not isinstance(size_kib, int) or size_kib < 0:
                size_kib = None
            if size_kib is None and install_path and os.path.exists(install_path):
                try:
                    total_bytes = sum(
                        f.stat().st_size for f in Path(install_path).glob("**/*") if f.is_file()
                    )
                    size_kib = max(1, total_bytes // 1024)
                except OSError:
                    pass

            apps.append(
                UnifiedApplication(
                    id=app_id,
                    name=item.get("name", "Portable App"),
                    source=SOURCE_PORTABLE,
                    version=item.get("version", ""),
                    icon=item.get("icon") or "application-x-executable",
                    executable=executable,
                    desktop_file=desktop_file,
                    install_path=install_path,
                    category="Utility",
                    package_name=item.get("name", ""),
                    update_available=False,
                    installed_size_kib=size_kib,
                    update_supported=False,
                    update_note="manual",
                    installed_date=item.get("installed_date", ""),
                    last_updated=item.get("last_updated", ""),
                )
            )

        if changed:
            save_portable_registry(reg)

        return sorted(apps, key=lambda a: a.name.lower())

    def remove(self, application: UnifiedApplication, purge: bool = False) -> None:
        """Taşınabilir uygulamayı sistemden kaldırır."""
        item = load_portable_registry().get(application.id)
        if not isinstance(item, dict) or item.get("install_path") != application.install_path:
            raise BackendError("Portable installation is not registered.")
        path = Path(application.install_path)
        validate_portable_path(path, item, application.id)
        desktop = Path(item["desktop_file"]) if item.get("desktop_file") else None
        apps_dir = _get_portable_registry_path().parent.parent / "applications"
        if desktop and (
            desktop.is_symlink()
            or desktop.parent.resolve() != apps_dir.resolve()
            or not desktop.name.startswith(("sourcedock-portable-", "voltapp-portable-"))
        ):
            raise BackendError("Unsafe portable desktop shortcut path.")
        try:
            if desktop and desktop.exists():
                desktop.unlink()
            shutil.rmtree(path)
        except OSError as exc:
            raise BackendError(f"Portable removal failed: {exc}") from exc
        unregister_portable_app(application.id)

        # 4. Masaüstü veritabanını yenile
        user_apps = str(apps_dir)
        if self.runner.command_exists("update-desktop-database"):
            self.runner.run(["update-desktop-database", user_apps], timeout=10, check=False)
