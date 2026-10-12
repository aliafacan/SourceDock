#!/usr/bin/env python3
"""Uygulama Mağazası (Flathub, Snap Store, APT) arama ve kurulum sağlayıcısı."""

from __future__ import annotations

from collections.abc import Callable
import os
import platform
import shutil
import subprocess
import time

from voltapp.core.errors import AuthRequiredError, BackendError, SnapClassicRequiredError
from voltapp.core.models import (
    APT_LOCK_NOWAIT,
    APT_LOCK_NOWAIT_VALUE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    StoreResult,
)


class StoreRegistry:
    """Mağazalardan (Flatpak, Snap, APT) arama ve kurulum işlemlerini yürüten sınıf."""

    def __init__(self):
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self.host_bridge_available = self._detect_host_bridge()
        self._current_process: subprocess.Popen | None = None

    def cancel_current(self) -> None:
        proc = self._current_process
        if proc and proc.poll() is None:
            proc.terminate()

    def set_sudo_password(self, password: str) -> None:
        self._sudo_password = password

    def clear_sudo_password(self) -> None:
        self._sudo_password = None

    def set_output_callback(self, callback: Callable[[str], None] | None) -> None:
        self._output_callback = callback

    def search(self, query: str, sources: set[str] | None = None) -> list[StoreResult]:
        if not query.strip():
            return []
        if sources is None:
            sources = {SOURCE_FLATPAK, SOURCE_SNAP, SOURCE_APT}
        results: list[StoreResult] = []
        if SOURCE_FLATPAK in sources:
            results.extend(self._search_flatpak(query))
        if SOURCE_SNAP in sources:
            results.extend(self._search_snap(query))
        if SOURCE_APT in sources:
            results.extend(self._search_apt(query))
        return results

    def _search_flatpak(self, query: str) -> list[StoreResult]:
        if not self._command_exists("flatpak"):
            return []
        try:
            result_with_size = self._run(
                ["flatpak", "search", query,
                 "--columns=name,application,description,version,remote,download-size"],
                timeout=30,
            )
            has_size = result_with_size.returncode == 0 and "\t" in result_with_size.stdout
            if has_size:
                raw = result_with_size
            else:
                raw = self._run(
                    ["flatpak", "search", query,
                     "--columns=name,application,description,version,remote"],
                    timeout=30,
                )

            items: list[StoreResult] = []
            for line in raw.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                name = parts[0].strip()
                app_id = parts[1].strip()
                if not name or not app_id:
                    continue
                desc = parts[2].strip() if len(parts) > 2 else ""
                version = parts[3].strip() if len(parts) > 3 else ""
                remote = parts[4].strip() if len(parts) > 4 else "flathub"
                size_str = parts[5].strip() if has_size and len(parts) > 5 else ""
                icon_path = self._flatpak_icon_path(app_id, remote)
                items.append(StoreResult(
                    name=name,
                    app_id=app_id,
                    description=desc,
                    source=SOURCE_FLATPAK,
                    version=version,
                    remote=remote,
                    download_size_str=size_str,
                    icon_path=icon_path,
                ))
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"Flatpak arama hatası: {exc}") from exc

    def _flatpak_icon_path(self, app_id: str, remote: str) -> str:
        arch = platform.machine() or "x86_64"
        search_dirs = [
            f"/var/lib/flatpak/appstream/{remote}/{arch}/active/icons",
            os.path.expanduser(f"~/.local/share/flatpak/appstream/{remote}/{arch}/active/icons"),
        ]
        for size_dir in ("128x128", "64x64"):
            for icons_dir in search_dirs:
                for ext in ("png", "svg"):
                    path = os.path.join(icons_dir, size_dir, f"{app_id}.{ext}")
                    if os.path.exists(path):
                        return path
        return ""

    def _search_snap(self, query: str) -> list[StoreResult]:
        if not self._command_exists("snap"):
            return []
        try:
            result = self._run(["snap", "find", query], timeout=30)
            items: list[StoreResult] = []
            for index, line in enumerate(result.stdout.splitlines()):
                if index == 0 or not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 1:
                    continue
                snap_name = parts[0]
                version = parts[1] if len(parts) > 1 else ""
                description = " ".join(parts[4:]) if len(parts) > 4 else ""
                items.append(StoreResult(
                    name=snap_name,
                    app_id=snap_name,
                    description=description,
                    source=SOURCE_SNAP,
                    version=version,
                    remote="snap-store",
                ))
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"Snap arama hatası: {exc}") from exc

    def _apt_candidate_versions(self, pkg_names: list[str]) -> dict[str, str]:
        if not pkg_names:
            return {}
        try:
            result = self._run(["apt-cache", "policy", "--"] + pkg_names, timeout=30)
            versions: dict[str, str] = {}
            current_pkg = ""
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if not line.startswith(" ") and stripped.endswith(":"):
                    current_pkg = stripped[:-1]
                elif current_pkg and stripped.startswith("Candidate:"):
                    ver = stripped.split(":", 1)[1].strip()
                    if ver and ver != "(none)":
                        versions[current_pkg] = ver
            return versions
        except Exception:
            return {}

    def _search_apt(self, query: str) -> list[StoreResult]:
        if not self._command_exists("apt-cache"):
            return []
        try:
            result = self._run(["apt-cache", "search", "--", query], timeout=30)
            items: list[StoreResult] = []
            pkg_names: list[str] = []
            raw_results: list[tuple[str, str]] = []
            for line in result.stdout.splitlines():
                if " - " not in line:
                    continue
                pkg_name, description = line.split(" - ", 1)
                pkg_name = pkg_name.strip()
                description = description.strip()
                if not pkg_name:
                    continue
                raw_results.append((pkg_name, description))
                pkg_names.append(pkg_name)
            raw_results = raw_results[:60]
            pkg_names = pkg_names[:60]
            versions = self._apt_candidate_versions(pkg_names)
            for pkg_name, description in raw_results:
                items.append(StoreResult(
                    name=pkg_name,
                    app_id=pkg_name,
                    description=description,
                    source=SOURCE_APT,
                    version=versions.get(pkg_name, ""),
                    remote="apt",
                ))
            return items
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"APT arama hatası: {exc}") from exc

    def install(self, result: StoreResult, classic: bool = False) -> None:
        if result.source == SOURCE_FLATPAK:
            self._install_flatpak(result)
        elif result.source == SOURCE_SNAP:
            self._install_snap(result, classic=classic)
        elif result.source == SOURCE_APT:
            self._install_apt(result)
        else:
            raise BackendError(f"Bilinmeyen kaynak: {result.source}")

    def _flatpak_remote_scope(self, remote: str) -> str:
        for scope_flag in ("--user", "--system"):
            r = self._run(["flatpak", "remotes", scope_flag, "--columns=name"], timeout=5)
            if r.returncode == 0:
                names = {line.strip().lower() for line in r.stdout.splitlines() if line.strip()}
                if remote.lower() in names:
                    return scope_flag
        return "--user"

    def _install_flatpak(self, result: StoreResult) -> None:
        remote = result.remote or "flathub"
        scope = self._flatpak_remote_scope(remote)
        cmd = ["flatpak", "install", scope, "-y", "--noninteractive", remote, result.app_id]
        if scope == "--system":
            self._run_privileged_streaming(cmd, timeout=1800)
        else:
            self._run_streaming(cmd, timeout=1800, check=True)

    def _install_snap(self, result: StoreResult, classic: bool = False) -> None:
        cmd = ["snap", "install"]
        if classic:
            cmd.append("--classic")
        cmd.append(result.app_id)
        self._run_privileged_streaming(cmd, timeout=1800, snap_pkg=result.app_id)

    def _install_apt(self, result: StoreResult) -> None:
        cmd = ["apt-get", APT_LOCK_NOWAIT, APT_LOCK_NOWAIT_VALUE, "install", "-y", result.app_id]
        self._run_privileged_streaming(cmd, timeout=1800)

    def _command_exists(self, command: str) -> bool:
        if self.host_bridge_available:
            r = self._run(["sh", "-lc", f"command -v {command} >/dev/null 2>&1"], timeout=5)
            return r.returncode == 0
        return shutil.which(command) is not None

    def _run(self, command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
        wrapped = self._wrap_host(command)
        try:
            return subprocess.run(
                wrapped,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(f"Komut çalıştırılamadı: {' '.join(command)}\n{exc}") from exc

    def _run_streaming(self, command: list[str], timeout: int = 1800, check: bool = False, snap_pkg: str = "") -> None:
        wrapped = self._wrap_host(command)
        collected: list[str] = []
        try:
            process = subprocess.Popen(
                wrapped,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._current_process = process
            try:
                buf = b""
                while True:
                    chunk = process.stdout.read(256)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        for sep in (b"\r\n", b"\n", b"\r"):
                            idx = buf.find(sep)
                            if idx >= 0:
                                line = buf[:idx].decode("utf-8", errors="replace").strip()
                                buf = buf[idx + len(sep):]
                                if line:
                                    collected.append(line)
                                    if self._output_callback:
                                        self._output_callback(line)
                                break
                        else:
                            break
                if buf:
                    line = buf.decode("utf-8", errors="replace").strip()
                    if line:
                        collected.append(line)
                        if self._output_callback:
                            self._output_callback(line)
            finally:
                self._current_process = None
            try:
                process.wait(timeout=max(5, timeout - 5))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise BackendError("Kurulum zaman aşımına uğradı.")
            if check and process.returncode != 0:
                combined = "\n".join(collected).lower()
                if snap_pkg and ("classic confinement" in combined or "--classic" in combined):
                    raise SnapClassicRequiredError(
                        f"Snap '{snap_pkg}' classic confinement gerektiriyor.",
                        package_name=snap_pkg,
                    )
                detail = "\n".join(collected[-5:]) if collected else ""
                err_msg = f"Komut başarısız oldu: {' '.join(command)}"
                if detail:
                    err_msg += f"\n{detail}"
                raise BackendError(err_msg)
        except OSError as exc:
            raise BackendError(f"Komut çalıştırılamadı: {' '.join(command)}\n{exc}") from exc

    def _run_privileged_streaming(self, command: list[str], timeout: int = 1800, snap_pkg: str = "") -> None:
        self._wait_for_apt_locks(command)
        sudo_probe = self._run(["sudo", "-n", "true"], timeout=5)
        if sudo_probe.returncode == 0:
            self._run_streaming(["sudo", "-n", *command], timeout=timeout, check=True, snap_pkg=snap_pkg)
            return

        if not self._sudo_password:
            raise AuthRequiredError(
                "Yönetici parolası gerekiyor. Snap kurulumu için parola gir.",
            )

        wrapped = self._wrap_host(["sudo", "-S", "-p", "", *command])
        try:
            process = subprocess.Popen(
                wrapped,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                process.stdin.write(f"{self._sudo_password}\n")  # type: ignore[union-attr]
                process.stdin.flush()  # type: ignore[union-attr]
                process.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass

            collected: list[str] = []
            for line in process.stdout:  # type: ignore[union-attr]
                stripped = line.rstrip()
                collected.append(stripped)
                if self._output_callback:
                    self._output_callback(stripped)

            try:
                process.wait(timeout=max(5, timeout - 5))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise BackendError("Kurulum zaman aşımına uğradı.")

            if process.returncode != 0:
                combined = "\n".join(collected).lower()
                if any(kw in combined for kw in ("password", "try again", "incorrect", "sorry")):
                    self.clear_sudo_password()
                    raise AuthRequiredError(
                        "Yönetici parolası hatalı. Lütfen tekrar dene.",
                        password_failed=True,
                    )
                if snap_pkg and ("classic confinement" in combined or "--classic" in combined):
                    raise SnapClassicRequiredError(
                        f"Snap '{snap_pkg}' classic confinement gerektiriyor.",
                        package_name=snap_pkg,
                    )
                detail = "\n".join(collected[-5:]) if collected else ""
                err_msg = f"Komut başarısız oldu: {' '.join(command)}"
                if detail:
                    err_msg += f"\n{detail}"
                raise BackendError(err_msg)
        except OSError as exc:
            raise BackendError(f"Komut çalıştırılamadı: {' '.join(command)}\n{exc}") from exc

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        started = time.monotonic()
        while True:
            holders = self._apt_lock_holders()
            if not holders:
                return
            summary = "; ".join(f"PID {pid}: {args}" for pid, args in holders[:3])
            if time.monotonic() - started >= max_wait:
                raise BackendError(f"APT şu anda başka bir işlem tarafından kullanılıyor.\n{summary}")
            time.sleep(2)

    def _apt_lock_holders(self) -> list[tuple[str, str]]:
        script = r'''
locks="/var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock /var/lib/apt/lists/lock"
pids=""
if command -v fuser >/dev/null 2>&1; then
  for lock in $locks; do
    [ -e "$lock" ] || continue
    found="$(fuser "$lock" 2>/dev/null || true)"
    pids="$pids $found"
  done
fi
pids="$(printf '%s\n' $pids | awk '!seen[$1]++')"
if [ -n "$pids" ]; then
  ps -p "$(printf '%s,' $pids | sed 's/,$//')" -o pid=,args= 2>/dev/null || true
else
  ps -eo pid=,args= | awk '/[a]pt |[a]pt-get |[d]pkg |[u]nattended-upgrade/ && !/wait-for-signal/ {print}'
fi
'''
        try:
            result = self._run(["sh", "-lc", script], timeout=5)
        except Exception:
            return []
        holders: list[tuple[str, str]] = []
        current_pid = str(os.getpid())
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid, args = parts
            if pid == current_pid:
                continue
            lowered = args.lower()
            if not any(token in lowered for token in ("apt", "apt-get", "dpkg", "unattended-upgrade")):
                continue
            holders.append((pid, args[:140]))
        return holders

    def _wrap_host(self, command: list[str]) -> list[str]:
        if self.host_bridge_available:
            return ["flatpak-spawn", "--host", *command]
        return command

    def _detect_host_bridge(self) -> bool:
        if not shutil.which("flatpak-spawn"):
            return False
        result = subprocess.run(
            ["flatpak-spawn", "--host", "true"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0

