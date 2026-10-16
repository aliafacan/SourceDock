#!/usr/bin/env python3
"""Sistem komut yürütücüsü ve yetki yönetimi."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.process import (
    NATIVE_OPERATION_LOCK,
    critical_command,
    redact_text,
    stream_process,
    terminate_process,
)


class CommandRunner:
    """Sistem komutlarını yürüten, yetkilendirme (sudo) ve akış (streaming) yöneten sınıf."""

    def __init__(self):
        self.host_bridge_available = self._detect_host_bridge()
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self._current_process: subprocess.Popen | None = None
        self._cancel_allowed = False
        self._cancelled = False

    def cancel_current(self) -> bool:
        """Çalışmakta olan aktif alt süreci sonlandırır."""
        proc = self._current_process
        if proc and proc.poll() is None and self._cancel_allowed:
            self._cancelled = True
            terminate_process(proc)
            try:
                proc.wait(timeout=0.8)
            except (subprocess.TimeoutExpired, OSError):
                terminate_process(proc, force=True)
            return True
        if self._cancel_allowed:
            self._cancelled = True
            return True
        return False

    def set_sudo_password(self, password: str) -> None:
        """Yönetici parolasını ayarlar."""
        self._sudo_password = password

    def clear_sudo_password(self) -> None:
        """Hafızadaki yönetici parolasını temizler."""
        self._sudo_password = None

    def set_output_callback(self, callback: Callable[[str], None] | None) -> None:
        """Komut çıktısı satır bazlı akarken tetiklenecek geri çağırma işlevi."""
        self._output_callback = callback

    def command_exists(self, command: str) -> bool:
        """Belirtilen komutun sistemde bulunup bulunmadığını kontrol eder."""
        if self.host_bridge_available:
            result = self.run(["sh", "-lc", f"command -v {shlex.quote(command)} >/dev/null 2>&1"], timeout=5)
            return result.returncode == 0
        return shutil.which(command) is not None

    def path_exists(self, path: str) -> bool:
        """Belirtilen dosya yolunun varlığını kontrol eder."""
        if self.host_bridge_available:
            result = self.run(["test", "-e", path], timeout=5)
            return result.returncode == 0
        return os.path.exists(path)

    def read_text(self, path: str) -> str:
        """Dosya içeriğini metin olarak okur."""
        if self.host_bridge_available and self.path_exists(path):
            result = self.run(["cat", path], timeout=10, check=True)
            return result.stdout

        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()

    def list_desktop_files(self, directories: list[str]) -> list[str]:
        """Verilen dizinlerdeki .desktop dosyalarını listeler."""
        if self.host_bridge_available:
            script = (
                'for dir in "$@"; do [ -d "$dir" ] && find "$dir" -maxdepth 1 -type f -name "*.desktop"; done'
            )
            result = self.run(["sh", "-c", script, "desktop-scan", *directories], timeout=15)
            if result.returncode == 0:
                return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})

        paths: list[str] = []
        for directory in directories:
            root = Path(directory).expanduser()
            if not root.exists():
                continue
            paths.extend(str(item) for item in root.glob("*.desktop") if item.is_file())
        return sorted(set(paths))

    def run(
        self,
        command: list[str],
        timeout: int = 30,
        check: bool = False,
        input_text: str | None = None,
        allow_cancel: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Standart bir komut çalıştırır."""
        wrapped = self._wrap_host(command)
        with NATIVE_OPERATION_LOCK if critical_command(wrapped) else nullcontext():
            if timeout >= 120 or self._output_callback is not None:
                return self._run_streaming(wrapped, timeout, check, stdin_text=input_text, allow_cancel=allow_cancel)
            return self._run_subprocess(wrapped, command, timeout, check, input_text, allow_cancel=allow_cancel)

    def run_read_only(
        self,
        command: list[str],
        timeout: int = 30,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a read-only query that can be cancelled as a provider times out."""
        wrapped = self._wrap_host(command)
        return self._run_subprocess(wrapped, command, timeout, check, None, allow_cancel=True)

    def _run_subprocess(
        self,
        wrapped: list[str],
        display_command: list[str],
        timeout: int,
        check: bool,
        input_text: str | None,
        allow_cancel: bool,
    ) -> subprocess.CompletedProcess[str]:
        process: subprocess.Popen[str] | None = None
        child_env = dict(os.environ)
        for name in (
            "GTK_PATH",
            "GTK3_MODULES",
            "GTK_EXE_PREFIX",
            "GTK_IM_MODULE_FILE",
            "GDK_PIXBUF_MODULEDIR",
            "GDK_PIXBUF_MODULE_FILE",
            "GIO_MODULE_DIR",
            "GSETTINGS_SCHEMA_DIR",
            "LOCPATH",
        ):
            child_env.pop(name, None)
        if "/snap/" in child_env.get("LD_LIBRARY_PATH", ""):
            child_env.pop("LD_LIBRARY_PATH", None)
        try:
            process = subprocess.Popen(
                wrapped,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=child_env,
            )
            self._current_process = process
            self._cancel_allowed = allow_cancel
            self._cancelled = False
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
            result = subprocess.CompletedProcess(wrapped, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                terminate_process(process, force=True)
                process.communicate()
            raise BackendError(
                redact_text(f"Komut calistirilamadi: {' '.join(display_command)}\n{exc}", (self._sudo_password,))
            ) from exc
        except OSError as exc:
            raise BackendError(
                redact_text(f"Komut calistirilamadi: {' '.join(display_command)}\n{exc}", (self._sudo_password,))
            ) from exc
        finally:
            self._current_process = None
            self._cancel_allowed = False

        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(
                redact_text(f"Komut basarisiz oldu: {' '.join(display_command)}\n{stderr}", (self._sudo_password,))
            )
        return result

    def _run_streaming(
        self,
        wrapped_command: list[str],
        timeout: int,
        check: bool,
        stdin_text: str | None = None,
        allow_cancel: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Komut çıktısını gerçek zamanlı olarak okur ve callback'e iletir."""
        with NATIVE_OPERATION_LOCK if critical_command(wrapped_command) else nullcontext():
            return self._run_streaming_locked(wrapped_command, timeout, check, stdin_text, allow_cancel=allow_cancel)

    def _run_streaming_locked(self, wrapped_command, timeout, check, stdin_text, allow_cancel=True):
        self._cancel_allowed = allow_cancel
        self._cancelled = False
        secrets = (self._sudo_password,)
        try:

            def started(process):
                self._current_process = process

            result = stream_process(
                wrapped_command,
                timeout,
                self._output_callback,
                stdin_text,
                started,
                secrets,
                lambda: self._cancelled,
            )
            if self._cancelled:
                raise BackendError("Operation cancelled.")
            if check and result.returncode != 0:
                tail = "\n".join(result.stdout.splitlines()[-3:])
                raise BackendError(redact_text(
                    f"Komut basarisiz oldu: {' '.join(wrapped_command)}\n{tail}", secrets,
                ))
            return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(redact_text(
                f"Komut calistirilamadi: {' '.join(wrapped_command)}\n{exc}", secrets,
            )) from None
        finally:
            self._current_process = None
            self._cancel_allowed = False

    def run_privileged(
        self,
        command: list[str],
        timeout: int = 900,
        input_text: str | None = None,
        allow_cancel: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Ayrıcalıklı (sudo) komut çalıştırır."""
        with NATIVE_OPERATION_LOCK:
            try:
                return self._run_privileged_locked(command, timeout, input_text, allow_cancel=allow_cancel)
            finally:
                self.clear_sudo_password()

    def _run_privileged_locked(self, command, timeout, input_text, allow_cancel=True):
        self._wait_for_apt_locks(command)
        sudo_probe = self.run(["sudo", "-n", "true"], timeout=5, allow_cancel=False)
        if sudo_probe.returncode == 0:
            result = self.run(["sudo", "-n", *command], timeout=timeout, input_text=input_text, allow_cancel=allow_cancel)
            self._raise_for_privileged_result(result, command)
            return result

        if not self._sudo_password:
            raise AuthRequiredError(
                "Yonetici parolasi gerekiyor. Canli onizlemeyi uygulama icinden acmak icin parolayi gir.",
            )

        stdin_text = f"{self._sudo_password}\n"
        if input_text is not None:
            stdin_text += input_text

        result = self.run(["sudo", "-S", "-p", "", *command], timeout=timeout, input_text=stdin_text, allow_cancel=allow_cancel)
        self._raise_for_privileged_result(result, command)
        return result

    def _raise_for_privileged_result(
        self,
        result: subprocess.CompletedProcess[str],
        command: list[str],
    ) -> None:
        if result.returncode != 0:
            combined = ((result.stderr or "") + "\n" + (result.stdout or "")).strip().lower()
            if any(kw in combined for kw in ("password", "try again", "incorrect", "sorry")):
                self.clear_sudo_password()
                raise AuthRequiredError(
                    "Yonetici parolasi hatali. Lutfen tekrar dene.",
                    password_failed=True,
                )
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(
                redact_text(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}", (self._sudo_password,))
            )

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        self._cancel_allowed = True
        self._cancelled = False
        started = time.monotonic()
        last_message = ""
        try:
            while True:
                if self._cancelled:
                    raise BackendError("Operation cancelled.")
                holders = self._apt_lock_holders()
                if not holders:
                    if last_message and self._output_callback is not None:
                        self._output_callback("APT kilidi boşaldı. İşleme devam ediliyor...")
                    return
                summary = "; ".join(f"PID {pid}: {args}" for pid, args in holders[:3])
                if len(holders) > 3:
                    summary += f"; +{len(holders) - 3} işlem"
                message = f"APT meşgul: {summary}"
                if message != last_message and self._output_callback is not None:
                    self._output_callback(message)
                    self._output_callback("Diğer APT işlemi bitince otomatik devam edilecek...")
                    last_message = message
                if time.monotonic() - started >= max_wait:
                    raise BackendError(f"APT şu anda başka bir işlem tarafından kullanılıyor.\n{summary}")
                sleep_end = time.monotonic() + 1.5
                while time.monotonic() < sleep_end:
                    if self._cancelled:
                        raise BackendError("Operation cancelled.")
                    time.sleep(0.1)
        finally:
            self._cancel_allowed = False

    def _apt_lock_holders(self) -> list[tuple[str, str]]:
        script = r"""
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
"""
        try:
            result = self.run(["sh", "-lc", script], timeout=5)
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
            if "wait-for-signal" in lowered:
                continue
            holders.append((pid, args[:140]))
        return holders

    def spawn(self, command: list[str]) -> None:
        """Yeni bir işlem başlatır (arka planda çalışması için)."""
        try:
            subprocess.Popen(
                self._wrap_host(command),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise BackendError(f"Komut calistirilamadi: {' '.join(command)}\n{exc}") from exc

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
