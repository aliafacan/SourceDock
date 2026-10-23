"""Non-blocking checks for newer SourceDock releases on GitHub."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from collections.abc import Callable
from urllib.request import Request, urlopen


GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/aliafacan/SourceDock/releases/latest"
DEFAULT_TIMEOUT = 6
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){1,3})$")


@dataclass(frozen=True)
class ReleaseInfo:
    """The small, validated subset of a GitHub release used by the UI."""

    version: str
    name: str
    url: str


def _version_key(value: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


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

    current_key = _version_key(current_version)
    if current_key is None:
        return None

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
        return None

    if not isinstance(payload, dict) or payload.get("draft") is True or payload.get("prerelease") is True:
        return None

    tag_name = payload.get("tag_name")
    if not isinstance(tag_name, str):
        return None
    version = tag_name.removeprefix("v")
    release_key = _version_key(version)
    if release_key is None or release_key <= current_key:
        return None

    release_url = payload.get("html_url")
    if not isinstance(release_url, str) or not release_url.startswith(("https://", "http://")):
        release_url = f"https://github.com/aliafacan/SourceDock/releases/tag/v{version}"
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        name = f"SourceDock v{version}"
    return ReleaseInfo(version=version, name=name.strip(), url=release_url)
