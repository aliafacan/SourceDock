#!/usr/bin/env python3
"""Linux dağıtımını ve etkin yerel paket yöneticisini tespit eden modül."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from voltapp.core.models import (
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_PACMAN,
    SOURCE_ZYPPER,
)

if TYPE_CHECKING:
    from voltapp.core.runner import CommandRunner


@dataclass(frozen=True)
class DistroInfo:
    """Tespit edilen Linux dağıtımı ve paket yöneticisi bilgileri."""

    id: str = "unknown"
    name: str = "Linux"
    pretty_name: str = "Linux"
    version_id: str = ""
    id_like: list[str] = field(default_factory=list)
    native_manager: str = SOURCE_APT

    @property
    def is_debian_family(self) -> bool:
        family = {self.id, *self.id_like}
        return bool(family.intersection({"debian", "ubuntu", "zorin", "mint", "pop", "elementary", "kali", "raspbian"}))

    @property
    def is_fedora_family(self) -> bool:
        family = {self.id, *self.id_like}
        return bool(family.intersection({"fedora", "rhel", "centos", "almalinux", "rocky", "ol", "amzn"}))

    @property
    def is_arch_family(self) -> bool:
        family = {self.id, *self.id_like}
        return bool(family.intersection({"arch", "manjaro", "endeavouros", "garuda", "artix", "cachyos", "steamos"}))

    @property
    def is_suse_family(self) -> bool:
        family = {self.id, *self.id_like}
        return bool(family.intersection({"suse", "opensuse", "opensuse-tumbleweed", "opensuse-leap", "sles"}))


def parse_os_release(content: str) -> dict[str, str]:
    """/etc/os-release dosya içeriğini anahtar-değer sözlüğüne çevirir."""
    data: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        data[key] = val
    return data


def detect_distro(
    runner: CommandRunner | None = None,
    os_release_path: str | Path | None = None,
) -> DistroInfo:
    """Sistemdeki Linux dağıtımını ve öncelikli yerel paket yöneticisini belirler."""
    os_data: dict[str, str] = {}

    paths_to_check = [os_release_path] if os_release_path else ["/etc/os-release", "/usr/lib/os-release"]
    for path_str in paths_to_check:
        if not path_str:
            continue
        p = Path(path_str)
        if p.exists() and p.is_file():
            try:
                os_data = parse_os_release(p.read_text(encoding="utf-8", errors="ignore"))
                if os_data:
                    break
            except OSError:
                pass

    distro_id = os_data.get("ID", "linux").lower()
    name = os_data.get("NAME", "Linux")
    pretty_name = os_data.get("PRETTY_NAME", name)
    version_id = os_data.get("VERSION_ID", "")
    id_like = [token.lower() for token in os_data.get("ID_LIKE", "").split() if token]

    def has_cmd(cmd: str) -> bool:
        if runner is not None:
            return runner.command_exists(cmd)
        return shutil.which(cmd) is not None

    family_tokens = {distro_id, *id_like}

    # 1. Dağıtım ailesine göre birincil paket yöneticisini öner
    preferred_manager = SOURCE_APT
    if family_tokens.intersection({"fedora", "rhel", "centos", "almalinux", "rocky", "ol", "amzn"}):
        preferred_manager = SOURCE_DNF
    elif family_tokens.intersection({"arch", "manjaro", "endeavouros", "garuda", "artix", "cachyos", "steamos"}):
        preferred_manager = SOURCE_PACMAN
    elif family_tokens.intersection({"suse", "opensuse", "opensuse-tumbleweed", "opensuse-leap", "sles"}):
        preferred_manager = SOURCE_ZYPPER
    elif family_tokens.intersection({"debian", "ubuntu", "zorin", "mint", "pop", "elementary", "kali"}):
        preferred_manager = SOURCE_APT

    # 2. Önerilen yönetici kurulu mu kontrol et, değilse sistemde olanı seç
    selected_manager = preferred_manager
    if preferred_manager == SOURCE_DNF and not (has_cmd("dnf") or has_cmd("rpm")):
        selected_manager = _find_available_manager(has_cmd)
    elif preferred_manager == SOURCE_PACMAN and not has_cmd("pacman"):
        selected_manager = _find_available_manager(has_cmd)
    elif preferred_manager == SOURCE_ZYPPER and not (has_cmd("zypper") or has_cmd("rpm")):
        selected_manager = _find_available_manager(has_cmd)
    elif preferred_manager == SOURCE_APT and not (has_cmd("apt-get") or has_cmd("dpkg")):
        selected_manager = _find_available_manager(has_cmd)

    return DistroInfo(
        id=distro_id,
        name=name,
        pretty_name=pretty_name,
        version_id=version_id,
        id_like=id_like,
        native_manager=selected_manager,
    )


def _find_available_manager(has_cmd: callable) -> str:
    """Sistemde kurulu ilk geçerli yerel paket yöneticisini bulur."""
    if has_cmd("apt-get") or has_cmd("dpkg"):
        return SOURCE_APT
    if has_cmd("dnf"):
        return SOURCE_DNF
    if has_cmd("pacman"):
        return SOURCE_PACMAN
    if has_cmd("zypper"):
        return SOURCE_ZYPPER
    return SOURCE_APT

