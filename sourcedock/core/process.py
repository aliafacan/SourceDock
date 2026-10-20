"""Deadline-aware subprocess streaming and redacted diagnostic output."""

from __future__ import annotations

import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time

from sourcedock.core.errors import BackendError

NATIVE_OPERATION_LOCK = threading.RLock()
CRITICAL_COMMANDS = {
    "apt", "apt-get", "dpkg", "dnf", "rpm", "pacman", "zypper", "flatpak", "snap",
    "fwupdmgr", "AppImageUpdate",
}


def redact_text(text: str, secrets=()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    home = str(Path.home())
    if home != "/":
        text = text.replace(home, "~")
    text = re.sub(r"(?<![\w])/(?:home/[^/\s]+|Users/[^/\s]+|root)(?=/|\s|$)", "~", text)
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", text)
    return re.sub(r"(?i)(password|token|secret|authorization)(\s*[:=]\s*)[^\s]+", r"\1\2[redacted]", text)


def critical_command(command: list[str]) -> bool:
    if not command:
        return False

    read_only = {
        "apt": {"list", "search", "show", "policy", "depends", "rdepends", "changelog"},
        "apt-get": {"check", "source", "changelog"},
        "dpkg": {"-s", "--status", "-l", "--list", "-L", "--listfiles", "-S", "--search"},
        "dnf": {"list", "info", "search", "check-update", "repoquery", "repolist"},
        "pacman": {"-Q", "-Qi", "-Ql", "-Qq", "-Qu", "-Qs", "-Si", "-Ss"},
        "zypper": {"search", "info", "list-updates", "repos"},
        "flatpak": {"list", "search", "info", "history", "remotes", "remote-info", "remote-ls"},
        "snap": {"list", "find", "info", "changes", "tasks", "version"},
        "fwupdmgr": {"get-devices", "get-updates", "get-history", "get-releases"},
    }

    # Detect scripts or explicit actions mutating packages / system state
    for arg in command:
        lower_arg = str(arg).lower()
        base_name = Path(arg).name.lower()
        if any(kw in lower_arg for kw in ("uninstall", "install", "remove", "purge", "dist-upgrade", "autoremove")):
            if lower_arg.endswith((".sh", ".bash", ".py", ".run")) or "uninstall" in base_name:
                return True

    for index, arg in enumerate(command[:6]):
        program = Path(arg).name
        if program not in CRITICAL_COMMANDS:
            continue
        arguments = iter(command[index + 1:])
        for action in arguments:
            if action in ("-o", "--option", "-c", "--config-file"):
                next(arguments, None)
                continue
            if action in read_only.get(program, set()):
                return False
            if action.startswith("-") and action != "--":
                continue
            return True
        return True
    return False


def terminate_process(process: subprocess.Popen, force: bool = False) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass


def stream_process(
    command,
    timeout,
    callback=None,
    input_text=None,
    on_start=None,
    secrets=(),
    cancelled=None,
    critical=False,
    allow_cancel=None,
):
    if allow_cancel is not None:
        critical = not allow_cancel
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
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_text else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=child_env,
        start_new_session=True,
    )
    lines = []
    MAX_STREAM_HISTORY = 5000
    buffer = b""
    deadline = time.monotonic() + timeout
    cancellation_deadline = None
    completed = False
    timeout_warned = False

    def emit(raw):
        line = redact_text(raw.decode("utf-8", errors="replace").strip(), secrets)
        if line:
            if len(lines) >= MAX_STREAM_HISTORY:
                lines.pop(0)
            lines.append(line)
            if callback:
                callback(line)

    try:
        if on_start:
            on_start(process)
        if input_text:
            try:
                process.stdin.write(input_text.encode("utf-8"))
                process.stdin.close()
            except BrokenPipeError:
                pass
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if cancelled and cancelled():
                    if cancellation_deadline is None:
                        cancellation_deadline = time.monotonic() + 0.5
                    elif time.monotonic() >= cancellation_deadline:
                        terminate_process(process, force=not critical)
                        raise BackendError("Operation cancelled.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if critical:
                        if callback:
                            callback(
                                "UYARI: Kritik paket işlemi zaman aşımına uğradı. "
                                "Veritabanı ve sistem bütünlüğünü korumak için süreç arka planda çalışmaya devam ediyor..."
                            )
                        raise BackendError(
                            f"Kritik paket işlemi zaman aşımına uğradı ({timeout}s). "
                            "Paket veritabanının bütünlüğünü korumak için zorla sonlandırılmadı ve süreç arka planda devam ediyor. "
                            "Lütfen işlem tamamlandığında paket yöneticisi durumunu (örn. 'sudo dpkg --configure -a') kontrol edin."
                        )
                    else:
                        raise BackendError("Command timed out.")
                for key, _mask in selector.select(min(0.2, max(0.01, remaining))):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer += chunk
                    while True:
                        match = re.search(rb"\r\n|\r|\n", buffer)
                        if match is None:
                            break
                        emit(buffer[: match.start()])
                        buffer = buffer[match.end() :]
                    if len(buffer) > 64 * 1024:
                        emit(buffer[: 64 * 1024])
                        buffer = buffer[64 * 1024 :]
            if buffer:
                emit(buffer)
            # Boru EOF verdi; ancak bu sürecin bittiği anlamına gelmez (P0-02)
            if process.poll() is None:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining > 0:
                    try:
                        process.wait(timeout=min(0.2, remaining))
                    except subprocess.TimeoutExpired:
                        pass
            process.poll()
            if process.returncode is None:
                if critical:
                    raise BackendError(
                        f"Kritik paket işlemi henüz tamamlanmadı ({timeout}s). "
                        "Paket veritabanının bütünlüğünü korumak için zorla sonlandırılmadı ve süreç arka planda devam ediyor. "
                        "Lütfen işlem tamamlandığında paket yöneticisi durumunu (örn. 'sudo dpkg --configure -a') kontrol edin."
                    )
                terminate_process(process, force=True)
                process.wait(timeout=2)
                raise BackendError("Command timed out.")
        completed = True
        return subprocess.CompletedProcess(command, process.returncode, "\n".join(lines), "")
    finally:
        if not completed or process.poll() is None:
            if not critical:
                terminate_process(process)
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    terminate_process(process, force=True)
                    process.wait(timeout=2)
            else:
                # Critical transaction: DO NOT send SIGTERM or SIGKILL on timeout or exception!
                pass
        # Kritik subprocess hâlâ yaşıyorsa boruyu kapatma (SIGPIPE/BrokenPipeError önlenir)
        if process.stdout and (completed or process.poll() is not None or not critical):
            try:
                process.stdout.close()
            except Exception:
                pass
        if process.stdin and not process.stdin.closed:
            try:
                process.stdin.close()
            except Exception:
                pass
        if on_start and (process.poll() is not None or not critical):
            on_start(None)
