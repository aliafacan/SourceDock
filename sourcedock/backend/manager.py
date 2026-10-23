#!/usr/bin/env python3
"""Tüm yüklü uygulama kaynaklarını birleştiren ve yöneten koordinatör (Registry)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
import re
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time

from sourcedock.core.errors import BackendError
from sourcedock.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    NATIVE_SOURCES,
    PACKAGE_MANAGER_SOURCES,
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_DNF,
    SOURCE_FLATPAK,
    SOURCE_PACMAN,
    SOURCE_PORTABLE,
    SOURCE_SNAP,
    SOURCE_ZYPPER,
    SOURCE_FIRMWARE,
    ApplicationIssue,
    ApplicationSnapshot,
    InstalledPackageStatus,
    LocalPackageInfo,
    PackageInfo,
    UnifiedApplication,
    is_native_source,
)
from sourcedock.core.runner import CommandRunner
from sourcedock.backend.base_native import BaseNativeProvider
from sourcedock.backend.distro import DistroInfo, detect_distro
from sourcedock.backend.scanner import (
    DesktopEntryScanner,
    _clean_exec_parts,
    _name_from_appimage,
    _normalize_name,
    _normalize_path,
)
from sourcedock.backend.apt import AptProvider
from sourcedock.backend.dnf import DnfProvider
from sourcedock.backend.pacman import PacmanProvider
from sourcedock.backend.zypper import ZypperProvider
from sourcedock.backend.flatpak import FlatpakProvider
from sourcedock.backend.snap import SnapProvider
from sourcedock.backend.firmware import FirmwareProvider
from sourcedock.backend.appimage import AppImageProvider
from sourcedock.backend.portable import PortableProvider


def _apt_command(*args: str) -> list[str]:
    return ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, *args]


def _flatpak_purge_data_path(app_id: str) -> Path:
    if (
        not isinstance(app_id, str)
        or len(app_id) > 255
        or not re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_]*\.){2,}[A-Za-z_-][A-Za-z0-9_-]*", app_id)
    ):
        raise BackendError("Invalid Flatpak application ID for data removal.")
    data_dir = Path.home() / ".var" / "app" / app_id
    try:
        for component in (data_dir, *data_dir.parents):
            if component.is_symlink():
                raise BackendError(f"Unsafe Flatpak data path: symbolic link at {component}")
            if component.exists() and not component.is_dir():
                raise BackendError(f"Unsafe Flatpak data path: not a directory at {component}")
    except OSError as exc:
        raise BackendError(f"Could not validate Flatpak data path {data_dir}: {exc}") from exc
    return data_dir


class ApplicationRegistry:
    """Sistemdeki tüm kurulu paket kaynaklarını yöneten ana kayıt defteri."""

    @staticmethod
    def _is_completed_success(res: object) -> bool:
        if res is None:
            return False
        returncode = getattr(res, "returncode", None)
        if isinstance(returncode, bool):
            return False
        if isinstance(returncode, int):
            return returncode == 0
        return False

    @staticmethod
    def _extract_error(res: object, fallback: str = "Komut basarisiz oldu") -> str:
        if res is None:
            return "İşlem sonucu geçersiz (boş)."
        stderr = getattr(res, "stderr", None)
        stdout = getattr(res, "stdout", None)
        msg = str(stderr or "").strip() or str(stdout or "").strip()
        return msg if msg else fallback


    # Provider commands have their own short command-level timeouts, but a
    # cold Flatpak metadata scan can legitimately take several seconds.  The
    # old five-second aggregate deadline routinely returned only AppImage and
    # firmware results and made the application list look incomplete.
    PROVIDER_TIMEOUT_SECONDS = 30.0
    APPLICATION_CACHE_TTL_SECONDS = 20.0
    PERSISTED_CACHE_TTL_SECONDS = 6 * 60 * 60

    def __init__(self, distro_info: DistroInfo | None = None, runner: CommandRunner | None = None):
        self.runner = runner or CommandRunner()
        self.scanner = DesktopEntryScanner(self.runner)
        self.distro = distro_info or detect_distro(self.runner)
        self.applications: list[UnifiedApplication] = []
        self.last_provider_metrics: dict[str, object] = {}
        self._application_cache: ApplicationSnapshot | None = None
        self._application_cache_at = 0.0
        self._application_cache_includes_updates = True
        self._application_cache_lock = threading.RLock()
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self._persisted_application_cache_path = cache_home / "sourcedock" / "installed-applications.json"

        self._native_providers: dict[str, BaseNativeProvider] = {
            SOURCE_APT: AptProvider(self.runner, self.scanner),
            SOURCE_DNF: DnfProvider(self.runner, self.scanner),
            SOURCE_PACMAN: PacmanProvider(self.runner, self.scanner),
            SOURCE_ZYPPER: ZypperProvider(self.runner, self.scanner),
        }
        self.native_provider = self._select_native_provider()

        self.providers = [
            self.native_provider,
            FlatpakProvider(self.runner, self.scanner),
            SnapProvider(self.runner, self.scanner),
            AppImageProvider(self.runner, self.scanner),
            PortableProvider(self.runner),
            FirmwareProvider(self.runner),
        ]

    def _select_native_provider(self) -> BaseNativeProvider:
        pref = self.distro.native_manager
        if pref in self._native_providers and self._native_providers[pref].is_available():
            return self._native_providers[pref]
        for mgr_key in (SOURCE_APT, SOURCE_DNF, SOURCE_PACMAN, SOURCE_ZYPPER):
            prov = self._native_providers[mgr_key]
            if prov.is_available():
                return prov
        return self._native_providers[SOURCE_APT]

    def get_native_provider(self, source: str | None = None) -> BaseNativeProvider:
        if source and source in self._native_providers:
            return self._native_providers[source]
        return self.native_provider

    def set_sudo_password(self, password: str) -> None:
        self.runner.set_sudo_password(password)

    def invalidate_application_cache(self, *, clear_persisted: bool = False) -> None:
        """Force the next read-only application load to query providers."""
        with self._application_cache_lock:
            self._application_cache = None
            self._application_cache_at = 0.0
        if clear_persisted:
            try:
                self._persisted_application_cache_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_persisted_application_cache(self) -> ApplicationSnapshot | None:
        """Load a short-lived last-known inventory for instant first paint."""
        cache_path = getattr(self, "_persisted_application_cache_path", None)
        if cache_path is None:
            return None
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            saved_at = float(raw.get("saved_at", 0))
            entries = raw.get("applications", [])
            if time.time() - saved_at > self.PERSISTED_CACHE_TTL_SECONDS or not isinstance(entries, list):
                return None
            allowed = set(UnifiedApplication.__dataclass_fields__)
            applications = []
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("id") or not entry.get("name"):
                    continue
                values = {key: value for key, value in entry.items() if key in allowed}
                applications.append(UnifiedApplication(**values))
            if not applications:
                return None
            return self._build_snapshot(applications, [])
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_persisted_application_cache(self, snapshot: ApplicationSnapshot) -> None:
        cache_path = getattr(self, "_persisted_application_cache_path", None)
        if cache_path is None:
            return
        try:
            from sourcedock.core.json_store import write_json

            write_json(
                cache_path,
                {"saved_at": time.time(), "applications": [asdict(app) for app in snapshot.applications]},
            )
        except (OSError, TypeError, ValueError):
            # The disk cache is an optimisation; a read-only or full cache
            # directory must never make application discovery fail.
            return

    def refresh_update_cache(self) -> None:
        if self.native_provider.is_available():
            cmd = self.native_provider.refresh_cache_command()
            if cmd:
                self.runner.run_privileged(cmd, timeout=120)
        if self.runner.command_exists("flatpak"):
            self.runner.run(["flatpak", "update", "--appstream", "-y"], timeout=60, check=False)
        if self.runner.command_exists("snap"):
            self.runner.run_privileged(["snap", "refresh", "--list"], timeout=30)
        if self.runner.command_exists("fwupdmgr"):
            self.runner.run(["fwupdmgr", "refresh", "--no-authenticate"], timeout=30, check=False)

    def refresh_update_cache_silent(self) -> None:
        try:
            sudo_res = self.runner.run(["sudo", "-n", "true"], timeout=5)
            sudo_free = self._is_completed_success(sudo_res)
            if sudo_free and self.native_provider.is_available():
                cmd = self.native_provider.refresh_cache_command()
                if cmd:
                    self.runner.run(["sudo", "-n", *cmd], timeout=90, check=False)
        except Exception:
            pass
        try:
            if self.runner.command_exists("flatpak"):
                self.runner.run(["flatpak", "update", "--appstream", "-y"], timeout=60, check=False)
        except Exception:
            pass
        try:
            if self.runner.command_exists("fwupdmgr"):
                self.runner.run(["fwupdmgr", "refresh", "--no-authenticate"], timeout=30, check=False)
        except Exception:
            pass

    def _load_provider(self, provider, include_updates: bool = True):
        started_at = time.perf_counter()
        try:
            if provider.source in {
                SOURCE_APT,
                SOURCE_FLATPAK,
                SOURCE_SNAP,
                SOURCE_FIRMWARE,
            }:
                try:
                    found = provider.list_applications(include_updates=include_updates)
                except TypeError as exc:
                    # Keep lightweight third-party/test providers compatible
                    # with the optional keyword introduced for staged scans.
                    if "include_updates" not in str(exc):
                        raise
                    found = provider.list_applications()
            else:
                found = provider.list_applications()
            return provider, found, None, (time.perf_counter() - started_at) * 1000
        except BackendError as exc:
            return provider, [], f"{provider.source}: {exc}", (time.perf_counter() - started_at) * 1000
        except Exception as exc:
            return provider, [], f"{provider.source}: {exc}", (time.perf_counter() - started_at) * 1000

    def _collect_provider_results(
        self,
        on_result: Callable[[list[UnifiedApplication], list[str]], None] | None = None,
        timeout_seconds: float | None = None,
        include_updates: bool = True,
        on_provider_result: Callable[[str, list[UnifiedApplication], str | None], None] | None = None,
    ) -> tuple[list[UnifiedApplication], list[str]]:
        """Collect independent read-only scans without waiting on a stalled provider.

        A timed-out worker is deliberately left to finish in the background. The
        returned snapshot is authoritative only for providers that completed; no
        destructive command is cancelled or retried from this path.
        """
        applications: list[UnifiedApplication] = []
        provider_errors: list[str] = []
        provider_metrics: dict[str, float] = {}
        timed_out: list[str] = []
        timeout = self.PROVIDER_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        executor = ThreadPoolExecutor(max_workers=max(1, min(6, len(self.providers))))
        future_to_provider = {
            executor.submit(self._load_provider, provider, include_updates): provider
            for provider in self.providers
        }
        pending = set(future_to_provider)
        started_at = time.perf_counter()
        deadline = None if timeout is None else started_at + max(0.0, timeout)

        try:
            while pending:
                remaining = None if deadline is None else max(0.0, deadline - time.perf_counter())
                done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                if not done:
                    break
                for future in done:
                    provider = future_to_provider[future]
                    result = future.result()
                    result_provider, found, error, *duration = result
                    source = result_provider.source if result_provider is not None else provider.source
                    provider_metrics[source] = round(
                        float(duration[0]) if duration else (time.perf_counter() - started_at) * 1000, 1
                    )
                    applications.extend(found)
                    if error:
                        provider_errors.append(error)
                    if on_provider_result:
                        on_provider_result(source, found, error)
                    if on_result:
                        on_result(applications, provider_errors)

            if pending:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
                for future in pending:
                    provider = future_to_provider[future]
                    timed_out.append(provider.source)
                    provider_metrics[provider.source] = elapsed_ms
                    error = (
                        f"{provider.source}: timeout after {timeout:g}s"
                        if timeout is not None
                        else f"{provider.source}: timeout"
                    )
                    provider_errors.append(error)
                    if on_provider_result:
                        on_provider_result(provider.source, [], error)
                    if on_result:
                        on_result(applications, provider_errors)
                    future.cancel()
        finally:
            # Do not make the UI thread wait for a provider that ignored its own
            # command timeout. Running workers are read-only and are not reused.
            executor.shutdown(wait=False, cancel_futures=True)

        self.last_provider_metrics = {
            "timeout_seconds": timeout,
            "sources": provider_metrics,
            "timed_out": timed_out,
            "completed": [source for source in provider_metrics if source not in timed_out],
        }
        return applications, provider_errors

    def _build_snapshot(
        self, applications: list[UnifiedApplication], provider_errors: list[str], include_hidden: bool = True
    ) -> ApplicationSnapshot:
        errors = list(provider_errors)
        notices: list[str] = []
        if include_hidden:
            hidden = getattr(self.native_provider, "_hidden_upgradable", set())
            if hidden:
                names = ", ".join(sorted(hidden))
                notices.append(
                    f"{self.native_provider.display_name.lower()} (sistem): {len(hidden)} arayüzsüz paket güncellenebilir → {names}"
                )

        merged = self._merge_applications(applications)
        self.applications = merged
        return ApplicationSnapshot(
            applications=merged,
            issues=self.diagnose(merged),
            provider_errors=errors,
            provider_notices=notices,
        )

    def load(
        self,
        provider_timeout_seconds: float | None = None,
        *,
        include_updates: bool = True,
    ) -> ApplicationSnapshot:
        with self._application_cache_lock:
            cached = self._application_cache
            cache_age = time.monotonic() - self._application_cache_at
        if (
            cached is not None
            and provider_timeout_seconds is None
            and (
                not include_updates
                or getattr(self, "_application_cache_includes_updates", True)
            )
            and cache_age <= self.APPLICATION_CACHE_TTL_SECONDS
        ):
            self.applications = cached.applications
            return cached
        applications, provider_errors = self._collect_provider_results(
            timeout_seconds=provider_timeout_seconds,
            include_updates=include_updates,
        )
        snapshot = self._build_snapshot(applications, provider_errors)
        if not provider_errors:
            with self._application_cache_lock:
                self._application_cache = snapshot
                self._application_cache_at = time.monotonic()
                self._application_cache_includes_updates = include_updates
            self._write_persisted_application_cache(snapshot)
        return snapshot

    def load_progressive(
        self,
        on_snapshot: Callable[[ApplicationSnapshot, bool], None],
        provider_timeout_seconds: float | None = None,
        *,
        include_updates: bool = True,
    ) -> ApplicationSnapshot:
        """Load providers concurrently and publish each completed snapshot."""
        applications: list[UnifiedApplication] = []
        provider_errors: list[str] = []

        persisted = self._read_persisted_application_cache()
        applications_by_source: dict[str, list[UnifiedApplication]] = {}
        if persisted is not None:
            # Show the last known inventory immediately. Fresh provider results
            # replace only their own source below, so a slow or unavailable
            # source does not make the whole cached list disappear.
            for application in persisted.applications:
                applications_by_source.setdefault(application.source, []).append(application)
            on_snapshot(persisted, False)

        def publish(_current_applications: list[UnifiedApplication], current_errors: list[str]) -> None:
            provider_errors[:] = current_errors
            applications[:] = [
                application
                for source_applications in applications_by_source.values()
                for application in source_applications
            ]
            on_snapshot(
                self._build_snapshot(applications, provider_errors, include_hidden=False), False
            )

        def publish_provider_result(
            source: str, found: list[UnifiedApplication], error: str | None
        ) -> None:
            # A failed source keeps its last known entries as a useful fallback;
            # a successful empty result deliberately removes that source.
            if error is None or source not in applications_by_source:
                applications_by_source[source] = list(found)

        collected_applications, collected_errors = self._collect_provider_results(
            on_result=publish,
            timeout_seconds=provider_timeout_seconds,
            include_updates=include_updates,
            on_provider_result=publish_provider_result,
        )
        if not applications_by_source:
            applications[:] = collected_applications
        else:
            applications[:] = [
                application
                for source_applications in applications_by_source.values()
                for application in source_applications
            ]
        provider_errors[:] = collected_errors

        snapshot = self._build_snapshot(applications, provider_errors)
        if not provider_errors:
            with self._application_cache_lock:
                self._application_cache = snapshot
                self._application_cache_at = time.monotonic()
                self._application_cache_includes_updates = include_updates
            self._write_persisted_application_cache(snapshot)
        on_snapshot(snapshot, True)
        return snapshot

    def list_packages(self) -> list[PackageInfo]:
        return self.native_provider.list_all_packages()

    def _update_native_packages_for_provider(self, prov: BaseNativeProvider, names: list[str]) -> None:
        if not names:
            return
        if prov.source == SOURCE_APT:
            self.runner.run_privileged(_apt_command("install", "--only-upgrade", "-y", *names), timeout=1800)
        elif prov.source == SOURCE_DNF:
            self.runner.run_privileged(["dnf", "upgrade", "-y", *names], timeout=1800)
        elif prov.source == SOURCE_PACMAN:
            self.runner.run_privileged(["pacman", "-S", "--noconfirm", *names], timeout=1800)
        elif prov.source == SOURCE_ZYPPER:
            self.runner.run_privileged(["zypper", "--non-interactive", "update", "-y", *names], timeout=1800)
        else:
            for name in names:
                self.runner.run_privileged(prov.update_command(name), timeout=1800)

    def update_packages(self, names: list[str]) -> None:
        if not names:
            return
        self._update_native_packages_for_provider(self.native_provider, names)

    def launch(self, application: UnifiedApplication) -> None:
        if application.source == SOURCE_FLATPAK:
            self.runner.spawn(["flatpak", "run", application.package_name])
            return
        if application.source == SOURCE_SNAP:
            command = _clean_exec_parts(application.executable) or [f"/snap/bin/{application.package_name}"]
            self.runner.spawn(command)
            return
        if application.source == SOURCE_APPIMAGE:
            self.runner.spawn([application.install_path])
            return
        if application.source == SOURCE_PORTABLE:
            if application.executable and os.path.exists(application.executable):
                self.runner.spawn([application.executable])
                return

        if (
            application.desktop_file
            and is_native_source(application.source)
            and self.runner.command_exists("gio")
        ):
            self.runner.spawn(["gio", "launch", application.desktop_file])
            return
        command = _clean_exec_parts(application.executable)
        if not command:
            raise BackendError("Uygulama komutu bulunamadi.")
        self.runner.spawn(command)

    def find_application(
        self, query: str, snapshot: ApplicationSnapshot | None = None
    ) -> UnifiedApplication | None:
        """Verilen paket adı, masaüstü ID'si, AppStream ID'si veya dosya yoluna göre kurulu uygulamayı bulur."""
        if not query:
            return None

        raw = query.strip()
        if raw.startswith("appstream://"):
            raw = raw.replace("appstream://", "")

        clean = raw[:-8] if raw.endswith(".desktop") else raw
        lower_raw = raw.lower()
        lower_clean = clean.lower()

        if snapshot is None:
            snapshot = self.load()

        # 1. Tam eşleşmeler (package_name, id, desktop_file basename)
        matches = []
        for app in snapshot.applications:
            pkg = app.package_name.lower() if app.package_name else ""
            app_id = app.id.lower()
            df_base = os.path.basename(app.desktop_file).lower() if app.desktop_file else ""
            if (
                pkg in (lower_raw, lower_clean)
                or app_id in (lower_raw, lower_clean)
                or df_base in (lower_raw, f"{lower_clean}.desktop")
                or app.desktop_file == raw
            ):
                matches.append(app)
        if not matches:
            matches = [app for app in snapshot.applications if app.name.lower() == lower_raw]
        identities = {(app.source, app.package_name or app.id) for app in matches}
        if len(identities) == 1:
            return matches[0]
        return None

        return None

    def open_location(self, application: UnifiedApplication) -> None:
        target = application.install_path or application.desktop_file
        if not target:
            raise BackendError("Konum bulunamadi.")
        if os.path.isfile(target):
            target = str(Path(target).parent)
        if self.runner.command_exists("xdg-open"):
            self.runner.spawn(["xdg-open", target])
            return
        self.runner.spawn(["gio", "open", target])

    def update(self, application: UnifiedApplication) -> None:
        if is_native_source(application.source):
            prov = self.get_native_provider(application.source)
            cmd = prov.update_command(application.package_name)
            self.runner.run_privileged(cmd, timeout=1800)
            return
        if application.source == SOURCE_FLATPAK:
            user_base = os.path.expanduser("~/.local/share/flatpak")
            scope = "--user" if application.install_path.startswith(user_base) else "--system"
            self.runner.run(
                ["flatpak", "update", scope, "-y", application.package_name], timeout=1800, check=True
            )
            return
        if application.source == SOURCE_SNAP:
            self.runner.run_privileged(["snap", "refresh", application.package_name], timeout=1800)
            return
        if application.source == SOURCE_APPIMAGE:
            if not application.update_supported:
                raise BackendError("Manual update required")
            self.runner.run(["AppImageUpdate", application.install_path], timeout=1800, check=True)
            return
        if application.source == SOURCE_FIRMWARE:
            self.runner.run(["fwupdmgr", "update", "-y", application.package_name], timeout=1800, check=True)
            return
        raise BackendError("Bilinmeyen uygulama kaynagi.")

    def update_all(self, applications: list[UnifiedApplication], whole_system: bool = False) -> None:
        if not applications:
            return

        failures: list[str] = []

        if whole_system:
            sources = {application.source for application in applications}
            for native_src in NATIVE_SOURCES:
                if native_src in sources:
                    prov = self.get_native_provider(native_src)
                    if prov and prov.is_available():
                        try:
                            self.runner.run_privileged(prov.update_all_command(), timeout=3600)
                        except Exception as exc:
                            failures.append(f"{prov.display_name}: {exc}")

            if SOURCE_FLATPAK in sources and self.runner.command_exists("flatpak"):
                try:
                    self.runner.run(["flatpak", "update", "-y"], timeout=3600, check=True)
                except Exception as exc:
                    failures.append(f"Flatpak: {exc}")
            if SOURCE_SNAP in sources and self.runner.command_exists("snap"):
                try:
                    self.runner.run_privileged(["snap", "refresh"], timeout=3600)
                except Exception as exc:
                    failures.append(f"Snap: {exc}")
            if SOURCE_FIRMWARE in sources and self.runner.command_exists("fwupdmgr"):
                res = self.runner.run(["fwupdmgr", "update", "-y"], timeout=3600, check=False)
                if not self._is_completed_success(res):
                    failures.append(f"Firmware: {self._extract_error(res, 'fwupdmgr update failed')}")
            for application in applications:
                if application.source == SOURCE_APPIMAGE and application.update_supported:
                    res = self.runner.run(["AppImageUpdate", application.install_path], timeout=1800, check=False)
                    if not self._is_completed_success(res):
                        failures.append(f"AppImage ({application.name}): {self._extract_error(res, 'AppImageUpdate failed')}")
            if failures:
                raise BackendError("Bazı güncellemeler başarısız oldu:\n" + "\n".join(failures))
            return

        # whole_system=False: Hedeflenen seçili paketler
        native_apps = [app for app in applications if is_native_source(app.source)]
        if native_apps:
            native_by_src: dict[str, list[str]] = {}
            for app in native_apps:
                native_by_src.setdefault(app.source, []).append(app.package_name)
            for src, names in native_by_src.items():
                prov = self.get_native_provider(src)
                if prov and prov.is_available():
                    try:
                        self._update_native_packages_for_provider(prov, names)
                    except Exception as exc:
                        failures.append(f"{prov.display_name} ({', '.join(names)}): {exc}")

        flatpak_apps = [app for app in applications if app.source == SOURCE_FLATPAK]
        if flatpak_apps and self.runner.command_exists("flatpak"):
            user_base = os.path.expanduser("~/.local/share/flatpak")
            for app in flatpak_apps:
                cmd = ["flatpak", "update"]
                if app.install_path.startswith(user_base):
                    cmd.append("--user")
                elif app.install_path.startswith("/var/lib/flatpak"):
                    cmd.append("--system")
                cmd.extend(["-y", app.package_name])
                res = self.runner.run(cmd, timeout=1800, check=False)
                if not self._is_completed_success(res):
                    failures.append(f"Flatpak ({app.name}): {self._extract_error(res, 'update failed')}")

        snap_apps = [app for app in applications if app.source == SOURCE_SNAP]
        if snap_apps and self.runner.command_exists("snap"):
            for app in snap_apps:
                try:
                    self.runner.run_privileged(["snap", "refresh", app.package_name], timeout=1800)
                except Exception as exc:
                    failures.append(f"Snap ({app.name}): {exc}")

        firmware_apps = [app for app in applications if app.source == SOURCE_FIRMWARE]
        if firmware_apps:
            if not self.runner.command_exists("fwupdmgr"):
                for app in firmware_apps:
                    failures.append(f"Firmware ({app.name}): fwupdmgr sistemi mevcut değil.")
            else:
                for app in firmware_apps:
                    device_id = app.package_name.strip()
                    if not device_id:
                        failures.append(
                            f"Firmware ({app.name}): Aygıt kimliği belirtilmedi; "
                            "seçili öğe için genel firmware güncellemesi başlatılamaz."
                        )
                        continue
                    # P0-04: Seçili firmware güncellemesi genel güncellemeye dönüşmez; aygıtı hedefler
                    res = self.runner.run(["fwupdmgr", "update", "-y", device_id], timeout=3600, check=False)
                    if not self._is_completed_success(res):
                        failures.append(f"Firmware ({app.name}): {self._extract_error(res, 'fwupdmgr update failed')}")

        for app in applications:
            if app.source == SOURCE_APPIMAGE and app.update_supported:
                res = self.runner.run(["AppImageUpdate", app.install_path], timeout=1800, check=False)
                if not self._is_completed_success(res):
                    failures.append(f"AppImage ({app.name}): {self._extract_error(res, 'AppImageUpdate failed')}")

        if failures:
            raise BackendError("Bazı güncellemeler tamamlanamadı:\n" + "\n".join(failures))

    def remove(self, application: UnifiedApplication, purge: bool = False) -> None:
        if is_native_source(application.source):
            prov = self.get_native_provider(application.source)
            cmd = prov.remove_command(application.package_name, purge=purge)
            self.runner.run_privileged(cmd, timeout=1800)
            if purge:
                self._remove_user_data_dirs(application.package_name)
            return
        if application.source == SOURCE_FLATPAK:
            if purge:
                _flatpak_purge_data_path(application.package_name)
            user_base = os.path.expanduser("~/.local/share/flatpak")
            scope = "--user" if application.install_path.startswith(user_base) else "--system"
            self.runner.run(
                ["flatpak", "uninstall", scope, "-y", application.package_name], timeout=1800, check=True
            )
            if purge:
                # Recheck after the provider operation, which can take minutes.
                data_dir = _flatpak_purge_data_path(application.package_name)
                try:
                    if data_dir.exists():
                        shutil.rmtree(data_dir)
                except OSError as exc:
                    raise BackendError(
                        f"Flatpak was uninstalled, but its data could not be removed at {data_dir}: {exc}"
                    ) from exc
                self._remove_user_data_dirs(application.package_name.rsplit(".", 1)[-1].lower())
            return
        if application.source == SOURCE_SNAP:
            cmd = ["snap", "remove"]
            if purge:
                cmd.append("--purge")
            cmd.append(application.package_name)
            self.runner.run_privileged(cmd, timeout=1800)
            return
        if application.source == SOURCE_APPIMAGE:
            self._remove_appimage(application)
            if purge:
                self._remove_user_data_dirs(application.name)
            return
        if application.source == SOURCE_PORTABLE:
            portable_provider = next((p for p in self.providers if isinstance(p, PortableProvider)), None)
            if portable_provider:
                portable_provider.remove(application, purge=purge)
            if purge:
                self._remove_user_data_dirs(application.name)
            return

    def remove_native_package(self, package_name: str, purge: bool = False) -> None:
        """Belirtilen native (APT/DNF/vb.) sistem paketini kaldırır."""
        prov = self.get_native_provider()
        cmd = prov.remove_command(package_name, purge=purge)
        self.runner.run_privileged(cmd, timeout=1800)

    def flatpak_cleanup(self, plan=None) -> None:
        if plan is None:
            raise BackendError("Review a Flatpak cleanup plan before removing components.")
        from sourcedock.backend.flatpak_cleanup import apply_cleanup

        apply_cleanup(self.runner, plan)

    def flatpak_history(self, app_id: str) -> list[dict]:
        result = self.runner.run(["flatpak", "remote-info", "--log", "flathub", app_id], timeout=30)
        entries: list[dict] = []
        current: dict = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Commit:"):
                if current:
                    entries.append(current)
                current = {"commit": line.split(":", 1)[1].strip(), "version": "", "date": ""}
            elif line.startswith("Version:") and current:
                current["version"] = line.split(":", 1)[1].strip()
            elif line.startswith("Date:") and current:
                current["date"] = line.split(":", 1)[1].strip()
        if current:
            entries.append(current)
        return entries

    def flatpak_rollback(self, app_id: str, commit: str) -> None:
        self.runner.run(["flatpak", "update", "--commit", commit, "-y", app_id], timeout=1800, check=True)

    def flatpak_permissions(self, app_id: str) -> dict[str, list[str]]:
        result = self.runner.run(["flatpak", "override", "--show", app_id], timeout=10)
        perms: dict[str, list[str]] = {}
        section = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                perms[section] = []
            elif line and section:
                perms[section].append(line)
        return perms

    def flatpak_reset_permissions(self, app_id: str) -> None:
        self.runner.run(["flatpak", "override", "--reset", app_id], timeout=15, check=True)

    def export_app_list(self) -> str:
        from sourcedock.core.app_lists import export_applications

        return export_applications(self.applications, self.distro)

    def apt_changelog(self, package_name: str) -> str:
        import gzip as _gzip

        for gz_path in (
            f"/usr/share/doc/{package_name}/changelog.Debian.gz",
            f"/usr/share/doc/{package_name}/changelog.gz",
        ):
            if os.path.exists(gz_path):
                try:
                    with _gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
                        return f.read()
                except Exception:
                    pass
        for txt_path in (
            f"/usr/share/doc/{package_name}/changelog.Debian",
            f"/usr/share/doc/{package_name}/changelog",
        ):
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()
                except Exception:
                    pass
        return ""

    def register_appimage(self, path: str) -> None:
        from sourcedock.backend.local_packages import install_local_appimage

        install_local_appimage(self.runner, path)

    def inspect_local_package(self, path: str) -> LocalPackageInfo:
        from sourcedock.backend.local_packages import inspect_local_package

        return inspect_local_package(self.runner, path)

    def is_local_package_installed(self, info: LocalPackageInfo) -> bool:
        from sourcedock.backend.local_packages import is_package_installed

        return is_package_installed(self.runner, info)

    def get_local_package_status(self, info: LocalPackageInfo) -> InstalledPackageStatus:
        from sourcedock.backend.local_packages import get_installed_package_status

        return get_installed_package_status(self.runner, info)

    def launch_local_package(self, info: LocalPackageInfo) -> bool:
        from sourcedock.backend.local_packages import launch_local_package

        return launch_local_package(self.runner, info)

    def install_local_package(
        self,
        info: LocalPackageInfo,
        target_dir: str | None = None,
        create_desktop: bool = True,
        scope: str = "--user",
        reinstall: bool = False,
    ) -> None:
        from sourcedock.backend.local_packages import (
            install_local_deb,
            install_local_appimage,
            install_local_archive,
            install_local_flatpak,
            install_local_rpm,
        )

        if info.format == "deb":
            install_local_deb(self.runner, info.file_path)
        elif info.format == "appimage":
            install_local_appimage(
                self.runner, info.file_path, target_dir=target_dir, create_desktop=create_desktop
            )
        elif info.format == "archive":
            install_local_archive(
                self.runner, info.file_path, extract_dir=target_dir, create_desktop=create_desktop
            )
        elif info.format in ("flatpakref", "flatpak"):
            install_local_flatpak(self.runner, info.file_path, scope=scope, reinstall=reinstall)
        elif info.format == "rpm":
            install_local_rpm(self.runner, info.file_path)
        else:
            raise BackendError(f"Desteklenmeyen paket formati: {info.format}")

    def _remove_user_data_dirs(self, name: str) -> None:
        # A display name does not establish ownership of a user's data directory.
        return

    def diagnose(self, applications: list[UnifiedApplication]) -> list[ApplicationIssue]:
        issues: list[ApplicationIssue] = []
        seen_names: dict[str, list[UnifiedApplication]] = {}
        for application in applications:
            key = _normalize_name(application.name)
            seen_names.setdefault(key, []).append(application)
            if not application.icon:
                issues.append(
                    ApplicationIssue(
                        "missing_icon", application.name, "No icon is set.", application.desktop_file
                    )
                )
            if application.desktop_file and not application.executable:
                issues.append(
                    ApplicationIssue(
                        "broken_desktop",
                        application.name,
                        "Desktop launcher has no command.",
                        application.desktop_file,
                    )
                )
            if (
                application.source == SOURCE_APPIMAGE
                and application.install_path
                and not os.path.exists(application.install_path)
            ):
                issues.append(
                    ApplicationIssue(
                        "broken_desktop",
                        application.name,
                        "Linked AppImage file is missing.",
                        application.desktop_file,
                    )
                )

        for duplicates in seen_names.values():
            source_set = {item.source for item in duplicates}
            if len(duplicates) > 1 and len(source_set) > 1:
                detail = ", ".join(sorted(item.source for item in duplicates))
                issues.append(ApplicationIssue("duplicate", duplicates[0].name, detail))
        return issues

    def _merge_applications(self, applications: list[UnifiedApplication]) -> list[UnifiedApplication]:
        by_id: dict[str, UnifiedApplication] = {}
        for application in applications:
            by_id[application.id] = application

        source_merged: dict[str, UnifiedApplication] = {}
        for application in by_id.values():
            key = self._dedupe_key(application)
            current = source_merged.get(key)
            if current is None or self._prefer(application, current):
                source_merged[key] = application

        return sorted(source_merged.values(), key=lambda app: (app.name.lower(), app.source))

    def _dedupe_key(self, application: UnifiedApplication) -> str:
        if application.source in PACKAGE_MANAGER_SOURCES:
            return f"{application.source}:{application.package_name}:{Path(application.desktop_file).name}"
        if application.install_path:
            return f"{application.source}:{application.install_path}"
        return f"{application.source}:{_normalize_name(application.name)}"

    def _prefer(self, candidate: UnifiedApplication, current: UnifiedApplication) -> bool:
        if candidate.desktop_file and not current.desktop_file:
            return True
        if candidate.update_available and not current.update_available:
            return True
        cand_in_apps = bool(candidate.install_path and "/applications" in candidate.install_path.lower())
        curr_in_apps = bool(current.install_path and "/applications" in current.install_path.lower())
        if cand_in_apps and not curr_in_apps:
            return True
        return len(candidate.name) > len(current.name)

    def _preference_sort_key(self, application: UnifiedApplication) -> tuple[int, int, int, int, str]:
        source_priority = {
            SOURCE_APT: 0,
            SOURCE_DNF: 0,
            SOURCE_PACMAN: 0,
            SOURCE_ZYPPER: 0,
            SOURCE_FLATPAK: 1,
            SOURCE_SNAP: 2,
            SOURCE_APPIMAGE: 3,
            SOURCE_PORTABLE: 4,
            SOURCE_FIRMWARE: 5,
        }.get(application.source, 9)
        in_apps = 0 if application.install_path and "/applications" in application.install_path.lower() else 1
        return (
            0 if application.update_available else 1,
            0 if application.desktop_file else 1,
            in_apps,
            source_priority,
            application.name.lower(),
        )

    def _remove_appimage(self, application: UnifiedApplication) -> None:
        if application.install_path and os.path.exists(application.install_path):
            os.remove(application.install_path)

        if not application.desktop_file or not os.path.exists(application.desktop_file):
            return

        try:
            entry = self.scanner.load_entry(application.desktop_file)
        except OSError:
            entry = None
        if entry and _normalize_path(entry.appimage_path) == _normalize_path(application.install_path):
            os.remove(application.desktop_file)
