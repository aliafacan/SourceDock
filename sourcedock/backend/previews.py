"""Read-only package plans. Never escalate privileges or execute package scripts.

Every function here only asks the native package manager to *calculate* a
transaction. Nothing is installed, no maintainer script runs, and
``run_privileged`` is never called. Command construction is covered by fake
runner tests so the arguments cannot silently drift.
"""

from pathlib import Path

from sourcedock.core.errors import BackendError

# Formats for which the installed native provider can compute a read-only plan.
SUPPORTED_PREVIEW_FORMATS = ("deb", "rpm")


def _resolve(file_path) -> str:
    return str(Path(file_path).resolve(strict=True))


def _plan_output(result, fallback: str) -> str:
    """Return provider output even when a dry-run exits non-zero.

    ``dnf install --assumeno`` and similar flags intentionally abort with a
    non-zero status after printing the planned transaction. The plan text is
    the useful result; a hard failure is only reported when no text exists.
    """
    text = (result.stdout or "").strip()
    if text:
        return text
    detail = (result.stderr or "").strip()
    if result.returncode != 0:
        raise BackendError(detail or fallback)
    return fallback


def preview_deb_install(runner, file_path):
    path = _resolve(file_path)
    if not runner.command_exists("apt-get"):
        raise BackendError("APT installation preview is unavailable on this system.")
    result = runner.run(
        ["apt-get", "--simulate", "-o", "Debug::NoLocking=true", "install", "--", path],
        timeout=30,
        check=False,
    )
    return _plan_output(result, "Could not calculate the installation plan.")


def preview_rpm_install(runner, file_path):
    """Preview a local .rpm transaction without installing it."""
    path = _resolve(file_path)
    if runner.command_exists("dnf"):
        result = runner.run(["dnf", "install", "--assumeno", path], timeout=45, check=False)
        return _plan_output(result, "Could not calculate the installation plan.")
    if runner.command_exists("zypper"):
        result = runner.run(
            ["zypper", "--non-interactive", "install", "--dry-run", path], timeout=45, check=False
        )
        return _plan_output(result, "Could not calculate the installation plan.")
    if runner.command_exists("rpm"):
        result = runner.run(["rpm", "-qpR", path], timeout=30, check=False)
        return _plan_output(result, "Could not read the package requirements.")
    raise BackendError("RPM installation preview is unavailable on this system.")


def preview_install_plan(runner, info):
    """Dispatch a read-only plan request for a local package preview.

    Unsupported formats raise a clear error so the interface can explain that a
    dependency plan is not offered rather than showing fabricated data.
    """
    package_format = getattr(info, "format", "")
    file_path = getattr(info, "file_path", "")
    if package_format == "deb":
        return preview_deb_install(runner, file_path)
    if package_format == "rpm":
        return preview_rpm_install(runner, file_path)
    raise BackendError("A read-only dependency preview is not available for this package format.")

def preview_native_upgrade(runner, package_names: list[str]) -> str:
    """Preview native package upgrades using dry-run simulation without modifying system."""
    if not package_names:
        return "No packages to upgrade."
    if runner.command_exists("apt-get"):
        result = runner.run(
            ["apt-get", "--simulate", "-o", "Debug::NoLocking=true", "install", "--only-upgrade", "-y", *package_names],
            timeout=30,
            check=False,
        )
        return _plan_output(result, "Could not calculate the upgrade plan.")
    if runner.command_exists("dnf"):
        result = runner.run(
            ["dnf", "upgrade", "--assumeno", *package_names],
            timeout=45,
            check=False,
        )
        return _plan_output(result, "Could not calculate the upgrade plan.")
    if runner.command_exists("zypper"):
        result = runner.run(
            ["zypper", "--non-interactive", "update", "--dry-run", *package_names],
            timeout=45,
            check=False,
        )
        return _plan_output(result, "Could not calculate the upgrade plan.")
    return "Upgrade preview is not supported on this package manager."
