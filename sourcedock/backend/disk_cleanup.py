"""Birleşik disk ve önbellek temizliği planlayıcı ve uygulayıcı (APT, Snap, Flatpak)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from sourcedock.backend.flatpak_cleanup import CleanupRef, apply_cleanup as apply_flatpak_cleanup, plan_cleanup as plan_flatpak_cleanup


@dataclass(frozen=True)
class SnapOldRevision:
    name: str
    revision: str
    size_bytes: int = 0


@dataclass
class DiskCleanupPlan:
    apt_cache_bytes: int = 0
    apt_cache_files: int = 0
    apt_cache_items: list[tuple[str, int]] = field(default_factory=list)
    apt_autoremove_packages: list[str] = field(default_factory=list)
    snap_old_revisions: list[SnapOldRevision] = field(default_factory=list)
    flatpak_refs: tuple[CleanupRef, ...] = ()

    @property
    def snap_bytes(self) -> int:
        return sum(item.size_bytes for item in self.snap_old_revisions)

    @property
    def total_known_bytes(self) -> int:
        return self.apt_cache_bytes + self.snap_bytes

    @property
    def has_anything(self) -> bool:
        return bool(
            self.apt_cache_files > 0
            or self.apt_autoremove_packages
            or self.snap_old_revisions
            or self.flatpak_refs
        )


def format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 MB"
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def plan_disk_cleanup(runner, native_manager: str = "apt") -> DiskCleanupPlan:
    """Sistemdeki temizlenebilir önbellek, eski snap revizyonları ve kullanılmayan bileşenleri tarar."""
    plan = DiskCleanupPlan()

    # 1. APT önbellek ve autoremove
    if native_manager == "apt" and runner.command_exists("apt-get"):
        cache_dir = Path("/var/cache/apt/archives")
        if cache_dir.is_dir():
            try:
                items: list[tuple[str, int]] = []
                for entry in cache_dir.iterdir():
                    if entry.is_file() and entry.suffix == ".deb":
                        size = entry.stat().st_size
                        plan.apt_cache_files += 1
                        plan.apt_cache_bytes += size
                        items.append((entry.name, size))
                plan.apt_cache_items = sorted(items, key=lambda pair: pair[1], reverse=True)
            except OSError:
                pass
        try:
            res = runner.run(["apt-get", "-s", "autoremove"], timeout=15, check=False)
            if getattr(res, "returncode", 1) == 0:
                pkgs: list[str] = []
                for line in (getattr(res, "stdout", "") or "").splitlines():
                    m = re.match(r"^Remv\s+(\S+)", line.strip())
                    if m:
                        pkgs.append(m.group(1))
                plan.apt_autoremove_packages = pkgs
        except Exception:
            pass

    # 2. Snap eski (devre dışı) revizyonlar
    if runner.command_exists("snap"):
        try:
            res = runner.run(["snap", "list", "--all"], timeout=10, check=False)
            if getattr(res, "returncode", 1) == 0:
                snaps_dir = Path("/var/lib/snapd/snaps")
                for line in (getattr(res, "stdout", "") or "").splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6 and "disabled" in parts[5].lower():
                        name, rev = parts[0], parts[2]
                        size_b = 0
                        snap_file = snaps_dir / f"{name}_{rev}.snap"
                        try:
                            if snap_file.is_file():
                                size_b = snap_file.stat().st_size
                        except OSError:
                            pass
                        plan.snap_old_revisions.append(SnapOldRevision(name=name, revision=rev, size_bytes=size_b))
        except Exception:
            pass

    # 3. Flatpak kullanılmayan bileşenler
    if runner.command_exists("flatpak"):
        try:
            plan.flatpak_refs = plan_flatpak_cleanup(runner)
        except Exception:
            plan.flatpak_refs = ()

    return plan


def apply_disk_cleanup(
    runner,
    plan: DiskCleanupPlan,
    *,
    clean_apt_cache: bool = False,
    clean_apt_autoremove: bool = False,
    clean_snap_old: bool = False,
    clean_flatpak: bool = False,
    selected_apt_autoremove: list[str] | None = None,
    selected_snap_revisions: list[SnapOldRevision] | None = None,
    selected_flatpak_refs: tuple[CleanupRef, ...] | None = None,
    on_progress=None,
) -> None:
    """Seçilen disk temizleme adımlarını uygular ve ilerleme bildirir."""
    auto_targets = (
        (selected_apt_autoremove if selected_apt_autoremove is not None else plan.apt_autoremove_packages)
        if (clean_apt_autoremove and plan.apt_autoremove_packages)
        else []
    )
    do_apt_cache = bool(clean_apt_cache and plan.apt_cache_files > 0)
    snap_targets = (
        (selected_snap_revisions if selected_snap_revisions is not None else plan.snap_old_revisions)
        if (clean_snap_old and plan.snap_old_revisions)
        else []
    )
    fp_targets = (
        (selected_flatpak_refs if selected_flatpak_refs is not None else plan.flatpak_refs)
        if (clean_flatpak and plan.flatpak_refs)
        else ()
    )

    total_steps = (
        (1 if auto_targets else 0)
        + (1 if do_apt_cache else 0)
        + len(snap_targets)
        + (1 if fp_targets else 0)
    )
    if total_steps == 0:
        return
    done_steps = 0

    def _report(msg: str) -> None:
        if callable(on_progress):
            on_progress(min(1.0, done_steps / total_steps), msg)

    if auto_targets:
        _report(f"APT autoremove ({len(auto_targets)})")
        if len(auto_targets) == len(plan.apt_autoremove_packages):
            runner.run_privileged(["apt-get", "-o", "DPkg::Lock::Timeout=0", "autoremove", "-y"], timeout=600)
        else:
            runner.run_privileged(["apt-get", "-o", "DPkg::Lock::Timeout=0", "remove", "-y", "--", *auto_targets], timeout=600)
        done_steps += 1
        _report(f"APT autoremove ({len(auto_targets)})")

    if do_apt_cache:
        _report("APT cache")
        runner.run_privileged(["apt-get", "-o", "DPkg::Lock::Timeout=0", "clean"], timeout=120)
        done_steps += 1
        _report("APT cache")

    for item in snap_targets:
        _report(f"Snap: {item.name} (rev {item.revision})")
        runner.run_privileged(["snap", "remove", item.name, f"--revision={item.revision}"], timeout=120)
        done_steps += 1
        _report(f"Snap: {item.name} (rev {item.revision})")

    if fp_targets:
        _report(f"Flatpak ({len(fp_targets)})")
        apply_flatpak_cleanup(runner, fp_targets)
        done_steps += 1
        _report(f"Flatpak ({len(fp_targets)})")
