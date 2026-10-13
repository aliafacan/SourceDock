#!/usr/bin/env python3
"""Sistem komut yürütücüsü ve yetki yönetimi."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

from voltapp.core.errors import AuthRequiredError, BackendError


class CommandRunner:
    """Sistem komutlarını yürüten, yetkilendirme (sudo) ve akış (streaming) yöneten sınıf."""

    def __init__(self):
        self.host_bridge_available = self._detect_host_bridge()
        self._sudo_password: str | None = None
        self._output_callback: Callable[[str], None] | None = None
        self._current_process: subprocess.Popen | None = None

    def cancel_current(self) -> None:
        """Çalışmakta olan aktif alt süreci sonlandırır."""
        proc = self._current_process
        if proc and proc.poll() is None:
            proc.terminate()

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
                'for dir in "$@"; do '
                '[ -d "$dir" ] && find "$dir" -maxdepth 1 -type f -name "*.desktop"; '
                "done"
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
    ) -> subprocess.CompletedProcess[str]:
        """Standart bir komut çalıştırır."""
        wrapped = self._wrap_host(command)
        if self._output_callback is not None and timeout >= 120:
            return self._run_streaming(wrapped, timeout, check, stdin_text=input_text)
        try:
            result = subprocess.run(
                wrapped,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(f"Komut calistirilamadi: {' '.join(command)}\n{exc}") from exc

        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "bilinmeyen hata"
            raise BackendError(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}")
        return result

    def _run_streaming(
        self,
        wrapped_command: list[str],
        timeout: int,
        check: bool,
        stdin_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Komut çıktısını gerçek zamanlı olarak okur ve callback'e iletir."""
        try:
            child_env = dict(os.environ)
            # Alt süreçlere snap ortam değişkenlerinin sızmasını önle
            for _v in (
                "GTK_PATH", "GTK3_MODULES", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
                "GDK_PIXBUF_MODULEDIR", "GDK_PIXBUF_MODULE_FILE", "GIO_MODULE_DIR",
                "GSETTINGS_SCHEMA_DIR", "LOCPATH",
            ):
                child_env.pop(_v, None)
            for _xv in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                if _xv in child_env and "/snap/" in child_env[_xv]:
                    child_env.pop(_xv, None)

            process = subprocess.Popen(
                wrapped_command,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=child_env,
            )
            self._current_process = process
            if stdin_text is not None:
                try:
                    encoded = stdin_text.encode("utf-8")
                    process.stdin.write(encoded)  # type: ignore[union-attr]
                    process.stdin.flush()  # type: ignore[union-attr]
                    process.stdin.close()  # type: ignore[union-attr]
                except OSError:
                    pass
            collected: list[str] = []
            buf = b""
            while True:
                try:
                    chunk = os.read(process.stdout.fileno(), 1024)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while True:
                    found = False
                    for sep in (b"\r\n", b"\n", b"\r"):
                        idx = buf.find(sep)
                        if idx >= 0:
                            line = buf[:idx].decode("utf-8", errors="replace").strip()
                            buf = buf[idx + len(sep):]
                            if line:
                                collected.append(line)
                                if self._output_callback is not None:
                                    self._output_callback(line)
                            found = True
                            break
                    if not found:
                        break
            if buf:
                line = buf.decode("utf-8", errors="replace").strip()
                if line:
                    collected.append(line)
                    if self._output_callback is not None:
                        self._output_callback(line)
            try:
                process.wait(timeout=max(5, timeout - 5))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise BackendError("Komut zaman asimina ugradi.")
            result = subprocess.CompletedProcess(
                args=wrapped_command,
                returncode=process.returncode,
                stdout="\n".join(collected),
                stderr="",
            )
            self._current_process = None
            if check and result.returncode != 0:
                tail = "\n".join(collected[-3:])
                raise BackendError(f"Komut basarisiz oldu: {' '.join(wrapped_command)}\n{tail}")
            return result
        except OSError as exc:
            self._current_process = None
            raise BackendError(f"Komut calistirilamadi: {' '.join(wrapped_command)}\n{exc}") from exc

    def run_privileged(
        self,
        command: list[str],
        timeout: int = 900,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Ayrıcalıklı (sudo) komut çalıştırır."""
        self._wait_for_apt_locks(command)
        sudo_probe = self.run(["sudo", "-n", "true"], timeout=5)
        if sudo_probe.returncode == 0:
            result = self.run(["sudo", "-n", *command], timeout=timeout, input_text=input_text)
            self._raise_for_privileged_result(result, command)
            return result

        if not self._sudo_password:
            raise AuthRequiredError(
                "Yonetici parolasi gerekiyor. Canli onizlemeyi uygulama icinden acmak icin parolayi gir.",
            )

        stdin_text = f"{self._sudo_password}\n"
        if input_text is not None:
            stdin_text += input_text

        result = self.run(["sudo", "-S", "-p", "", *command], timeout=timeout, input_text=stdin_text)
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
            raise BackendError(f"Komut basarisiz oldu: {' '.join(command)}\n{stderr}")

    def _wait_for_apt_locks(self, command: list[str], max_wait: int = 300) -> None:
        if not command or command[0] not in {"apt", "apt-get", "nala", "dpkg"}:
            return
        started = time.monotonic()
        last_message = ""
        while True:
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

