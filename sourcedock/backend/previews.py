"""Read-only package plans. Never escalate privileges or execute package scripts."""

from pathlib import Path

from sourcedock.core.errors import BackendError


def preview_deb_install(runner, file_path):
    path = str(Path(file_path).resolve(strict=True))
    if not runner.command_exists("apt-get"):
        raise BackendError("APT installation preview is unavailable on this system.")
    result = runner.run(
        ["apt-get", "--simulate", "-o", "Debug::NoLocking=true", "install", "--", path],
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise BackendError(result.stderr or result.stdout or "Could not calculate the installation plan.")
    return result.stdout
