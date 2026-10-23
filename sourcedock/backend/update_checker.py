"""Non-blocking checks for newer SourceDock releases on GitHub."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from collections.abc import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen


GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/aliafacan/SourceDock/releases/latest"
DEFAULT_TIMEOUT = 6
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")


@dataclass(frozen=True)
class ReleaseInfo:
    """The small, validated subset of a GitHub release used by the UI."""

    version: str
    name: str
    url: str
    deb_url: str | None = None
    checksum_url: str | None = None


@dataclass(frozen=True)
class ReleaseCheckResult:
    """Result of a release check, including a useful no-update status."""

    release: ReleaseInfo | None
    status: str


def _version_key(value: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _is_github_release_asset(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "github.com"
        and parsed.path.startswith("/aliafacan/SourceDock/releases/download/")
    )


def check_latest_release(
    current_version: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: int = DEFAULT_TIMEOUT,
) -> ReleaseInfo | None:
    """Return a newer stable release, or ``None`` when it cannot be checked.

    This function intentionally treats network and payload errors as a normal
    no-result. A release check must never make SourceDock startup or browsing
    fail when GitHub is unavailable.
    """

    return check_latest_release_result(
        current_version,
        opener=opener,
        timeout=timeout,
    ).release


def check_latest_release_result(
    current_version: str,
    *,
    opener: Callable[..., object] = urlopen,
    timeout: int = DEFAULT_TIMEOUT,
) -> ReleaseCheckResult:
    """Return update, up-to-date, or unavailable status for a release check."""

    current_key = _version_key(current_version)
    if current_key is None:
        return ReleaseCheckResult(None, "unavailable")

    request = Request(
        GITHUB_LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"SourceDock/{current_version}",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError, TypeError, AttributeError):
        return ReleaseCheckResult(None, "unavailable")

    if not isinstance(payload, dict) or payload.get("draft") is True or payload.get("prerelease") is True:
        return ReleaseCheckResult(None, "unavailable")

    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str):
        return ReleaseCheckResult(None, "unavailable")
    version = tag_name.removeprefix("v")
    release_key = _version_key(version)
    if release_key is None:
        return ReleaseCheckResult(None, "unavailable")
    if release_key <= current_key:
        return ReleaseCheckResult(None, "up_to_date")

    release_url = payload.get("html_url")
    if not isinstance(release_url, str) or not release_url.startswith(("https://", "http://")):
        release_url = f"https://github.com/aliafacan/SourceDock/releases/tag/v{version}"
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        name = f"SourceDock v{version}"

    expected_deb_name = f"sourcedock_{version}_all.deb"
    deb_url = None
    checksum_url = None
    assets = payload.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_name = asset.get("name")
            asset_url = asset.get("browser_download_url")
            if not isinstance(asset_name, str) or not _is_github_release_asset(asset_url):
                continue
            if asset_name == expected_deb_name:
                deb_url = asset_url
            elif asset_name == f"{expected_deb_name}.sha256":
                checksum_url = asset_url

    return ReleaseCheckResult(
        ReleaseInfo(
            version=version,
            name=name.strip(),
            url=release_url,
            deb_url=deb_url,
            checksum_url=checksum_url,
        ),
        "update_available",
    )


def _download_bytes(opener: Callable[..., object], url: str, *, timeout: int, limit: int) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "SourceDock",
        },
    )
    chunks: list[bytes] = []
    total = 0
    with opener(request, timeout=timeout) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("Downloaded release asset is too large")
            chunks.append(chunk)
    return b"".join(chunks)


def download_release_package(
    release: ReleaseInfo,
    *,
    destination_dir: str | os.PathLike[str] | None = None,
    opener: Callable[..., object] = urlopen,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Download and verify the signed-by-checksum release DEB.

    The returned path is in SourceDock's own cache directory. The file is
    written through a temporary sibling and atomically replaced only after the
    checksum matches, so an interrupted download cannot become installable.
    """

    if not release.deb_url or not release.checksum_url:
        raise ValueError("This release does not provide a verified DEB asset")
    if not _is_github_release_asset(release.deb_url) or not _is_github_release_asset(release.checksum_url):
        raise ValueError("Release assets must come from the SourceDock GitHub release")

    if destination_dir is None:
        cache_home = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        destination = Path(cache_home) / "sourcedock" / "updates"
    else:
        destination = Path(destination_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)

    package_path = destination / f"sourcedock_{release.version}_all.deb"
    temporary_path = package_path.with_suffix(package_path.suffix + ".part")
    package_data = _download_bytes(opener, release.deb_url, timeout=timeout, limit=MAX_DOWNLOAD_BYTES)
    checksum_data = _download_bytes(opener, release.checksum_url, timeout=timeout, limit=64 * 1024)
    try:
        checksum_text = checksum_data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Release checksum is missing or invalid") from exc
    checksum_lines = [line.strip() for line in checksum_text.splitlines() if line.strip()]
    if len(checksum_lines) != 1:
        raise ValueError("Release checksum is missing or invalid")
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?([^\s]+)", checksum_lines[0])
    if match is None or Path(match.group(2)).name != package_path.name:
        raise ValueError("Release checksum is missing or invalid")
    actual_checksum = hashlib.sha256(package_data).hexdigest()
    if not hmac.compare_digest(actual_checksum.lower(), match.group(1).lower()):
        raise ValueError("Release checksum verification failed")

    try:
        temporary_path.write_bytes(package_data)
        os.replace(temporary_path, package_path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    return str(package_path)
