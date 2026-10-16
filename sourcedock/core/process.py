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
    command, timeout, callback=None, input_text=None, on_start=None, secrets=(), cancelled=None
):
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
    buffer = b""
    deadline = time.monotonic() + timeout
    cancellation_deadline = None
    completed = False

    def emit(raw):
        line = redact_text(raw.decode("utf-8", errors="replace").strip(), secrets)
        if line:
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
                        cancellation_deadline = time.monotonic() + 1
                    elif time.monotonic() >= cancellation_deadline:
                        terminate_process(process, force=True)
                        raise BackendError("Operation cancelled.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BackendError("Command timed out.")
                for key, _mask in selector.select(min(0.2, remaining)):
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
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        completed = True
        return subprocess.CompletedProcess(command, process.returncode, "\n".join(lines), "")
    finally:
        if not completed or process.poll() is None:
            terminate_process(process)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                terminate_process(process, force=True)
                process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if on_start:
            on_start(None)
