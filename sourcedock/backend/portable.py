#!/usr/bin/env python3
"""Taşınabilir (Portable / Archive) uygulamalar sağlayıcısı ve kayıt yöneticisi."""

from __future__ import annotations

from datetime import datetime
from configparser import ConfigParser, Error as ConfigError
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import uuid

from sourcedock.core.errors import BackendError
from sourcedock.core.json_store import write_json
from sourcedock.core.models import SOURCE_PORTABLE, UnifiedApplication
from sourcedock.core.runner import CommandRunner
from sourcedock.core.transactions import serialized_resource
from sourcedock.backend.scanner import _clean_exec_command, _normalize_path
from sourcedock.backend.desktop_entries import electron_desktop_exec


SYSTEM_PORTABLE_APPS_ROOT = Path("/opt")
USER_PORTABLE_APPS_ROOT = Path.home() / ".local" / "opt"
LEGACY_PORTABLE_APPS_ROOT_NAME = "apps"


def repair_electron_launcher(application):
    """Match both Electron's startup class and its final product window class."""
    item = load_portable_registry().get(application.id)
    if not isinstance(item, dict) or item.get("desktop_file") != application.desktop_file:
        return False
    desktop = Path(application.desktop_file)
    apps_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    if (desktop.is_symlink() or desktop.parent.resolve() != apps_dir.resolve()
            or not desktop.name.startswith(("sourcedock-portable-", "voltapp-portable-"))):
        return False
    executable = Path(item.get("executable", ""))
    root = Path(item.get("install_path", ""))
    if not executable.is_relative_to(root) or not (executable.parent / "resources/app/product.json").is_file():
        return False
    try:
        validate_portable_path(root, item, application.id)
        parser = ConfigParser(interpolation=None)
        parser.optionxform = str
        original = desktop.read_text(encoding="utf-8")
        parser.read_string(original)
        entry = parser["Desktop Entry"]
        if entry.get("X-SourceDock-Managed") != "true":
            return False
        from sourcedock.backend.local_packages import _read_electron_product

        product = _read_electron_product(executable)
        if not product:
            return False
        entry["Exec"] = electron_desktop_exec(executable, desktop.stem)
        # Respect a bundled class; older generated classes need migration.
        old_class = entry.get("StartupWMClass", "")
        app_name = product.get("applicationName") or executable.stem
        generated_classes = {desktop.stem, app_name, app_name[:1].upper() + app_name[1:], ""}
        if old_class in generated_classes:
            entry["StartupWMClass"] = product.get("nameShort") or app_name[:1].upper() + app_name[1:]
        buffer = StringIO()
        parser.write(buffer, space_around_delimiters=False)
        updated = buffer.getvalue()
        if original != updated:
            desktop.write_text(updated, encoding="utf-8")
            return True
    except (OSError, ValueError, KeyError, ConfigError, BackendError):
        return False
    return False


def get_portable_apps_root() -> Path:
    """Return the system-style portable root, falling back to the user directory."""
    custom_data_home = os.environ.get("XDG_DATA_HOME")
    if custom_data_home:
        return Path(custom_data_home) / "sourcedock" / LEGACY_PORTABLE_APPS_ROOT_NAME
    if os.access(SYSTEM_PORTABLE_APPS_ROOT, os.W_OK):
        return SYSTEM_PORTABLE_APPS_ROOT
    return USER_PORTABLE_APPS_ROOT


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
    root = Path(managed_root) if managed_root else get_portable_apps_root()
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


def find_portable_app(name: str) -> UnifiedApplication | None:
    """Return a registered portable application matching its display name."""
    normalized_name = name.strip().casefold()
    if not normalized_name:
        return None

    for app_id, item in load_portable_registry().items():
        if not isinstance(item, dict) or str(item.get("name", "")).strip().casefold() != normalized_name:
            continue
        return UnifiedApplication(
            id=app_id,
            name=item.get("name", "Portable App"),
            source=SOURCE_PORTABLE,
            version=item.get("version", ""),
            icon=item.get("icon") or "application-x-executable",
            executable=item.get("executable", ""),
            desktop_file=item.get("desktop_file", ""),
            install_path=item.get("install_path", ""),
            category="Utility",
            package_name=item.get("name", ""),
            update_available=False,
            installed_size_kib=item.get("size_kib") if isinstance(item.get("size_kib"), int) else None,
            update_supported=False,
            update_note="",
            installed_date=item.get("installed_date", ""),
            last_updated=item.get("last_updated", ""),
        )
    return None


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
                    update_note="",
                    installed_date=item.get("installed_date", ""),
                    last_updated=item.get("last_updated", ""),
                )
            )
            repair_electron_launcher(apps[-1])

        if changed:
            save_portable_registry(reg)

        return sorted(apps, key=lambda a: a.name.lower())

    @serialized_resource("sourcedock-portable")
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
