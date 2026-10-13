#!/usr/bin/env python3
"""Donanım bellenimi (firmware / fwupd) güncellemeleri sağlayıcısı."""

from __future__ import annotations

import json
from typing import Any

from voltapp.core.models import (
    SOURCE_FIRMWARE,
    UnifiedApplication,
)
from voltapp.core.runner import CommandRunner


class FirmwareProvider:
    """Sistem donanım yazılımlarını (UEFI, Secure Boot dbx vb.) yöneten ve listeleyen sağlayıcı."""

    source = SOURCE_FIRMWARE

    def __init__(self, runner: CommandRunner):
        self.runner = runner

    def is_available(self) -> bool:
        return self.runner.command_exists("fwupdmgr")

    def list_applications(self) -> list[UnifiedApplication]:
        if not self.is_available():
            return []

        try:
            result = self.runner.run(
                ["fwupdmgr", "get-updates", "--json", "--no-authenticate"],
                timeout=15,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []

            data: dict[str, Any] = json.loads(result.stdout)
            devices = data.get("Devices", [])
            applications: list[UnifiedApplication] = []

            for dev in devices:
                device_id = str(dev.get("DeviceId") or dev.get("AppstreamId") or dev.get("Name") or "").strip()
                if not device_id:
                    continue

                name = str(dev.get("Name") or device_id).strip()
                summary = str(dev.get("Summary") or "").strip()
                current_ver = str(dev.get("Version") or "").strip()

                releases = dev.get("Releases", [])
                new_ver = ""
                if isinstance(releases, list) and releases:
                    new_ver = str(releases[0].get("Version") or "").strip()

                display_name = f"{name} ({summary})" if summary and summary != name else name

                applications.append(
                    UnifiedApplication(
                        id=f"{SOURCE_FIRMWARE}:{device_id}",
                        name=display_name,
                        source=SOURCE_FIRMWARE,
                        version=current_ver,
                        icon="system-run",
                        executable="",
                        desktop_file="",
                        install_path="",
                        category="System",
                        package_name=device_id,
                        update_available=True,
                        update_note=f"-> {new_ver}" if new_ver else "",
                        installed_size_kib=None,
                        installed_date="",
                        last_updated="",
                    )
                )

            return applications
        except Exception:
            return []

    def update_command(self, device_id: str | None = None) -> list[str]:
        if device_id:
            return ["fwupdmgr", "update", "-y", device_id]
        return ["fwupdmgr", "update", "-y"]

    def update_all_command(self) -> list[str]:
        return ["fwupdmgr", "update", "-y"]

    def refresh_cache_command(self) -> list[str]:
        return ["fwupdmgr", "refresh", "--no-authenticate"]
