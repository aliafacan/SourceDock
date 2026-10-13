#!/usr/bin/env python3
"""Taşınabilir (Portable / Archive) uygulamalar sağlayıcısı ve kayıt yöneticisi."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil

from voltapp.core.models import SOURCE_PORTABLE, UnifiedApplication
from voltapp.core.runner import CommandRunner
from voltapp.backend.scanner import _clean_exec_command, _normalize_path


def _get_portable_registry_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    base = data_home / "voltapp"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base / "portable_registry.json"


def load_portable_registry() -> dict[str, dict]:
    path = _get_portable_registry_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_portable_registry(registry: dict[str, dict]) -> None:
    path = _get_portable_registry_path()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(registry, fh, indent=2, ensure_ascii=False)
    except Exception:
        pass


def register_portable_app(
    name: str,
    version: str,
    install_path: str,
    executable: str,
    desktop_file: str,
    icon: str = "",
    size_kib: int | None = None,
) -> None:
    reg = load_portable_registry()
    app_id = f"{SOURCE_PORTABLE}:{name.lower().replace(' ', '_')}"
    today = datetime.now().strftime("%Y-%m-%d")
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
    }
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
            install_path = item.get("install_path", "")
            executable = item.get("executable", "")
            desktop_file = item.get("desktop_file", "")

            # Eğer kurulum klasörü veya çalıştırılabilir dosya silinmişse listeden temizle
            if (install_path and not os.path.exists(install_path)) and (executable and not os.path.exists(executable)):
                del reg[app_id]
                changed = True
                continue

            size_kib = item.get("size_kib")
            if size_kib is None and install_path and os.path.exists(install_path):
                try:
                    total_bytes = sum(
                        f.stat().st_size
                        for f in Path(install_path).glob("**/*")
                        if f.is_file()
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
        # 1. Kurulum dizinini temizle
        if application.install_path and os.path.exists(application.install_path):
            shutil.rmtree(application.install_path, ignore_errors=True)

        # 2. .desktop kısayolunu temizle
        if application.desktop_file and os.path.exists(application.desktop_file):
            try:
                os.remove(application.desktop_file)
            except OSError:
                pass

        # 3. Kayıt defterinden sil
        unregister_portable_app(application.id)

        # 4. Masaüstü veritabanını yenile
        user_apps = os.path.expanduser("~/.local/share/applications")
        if self.runner.command_exists("update-desktop-database"):
            self.runner.run(["update-desktop-database", user_apps], timeout=10, check=False)
