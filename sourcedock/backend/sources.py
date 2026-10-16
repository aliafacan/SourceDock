"""Read configured sources without editing repositories or changing channels."""

from email.parser import Parser
from pathlib import Path
import re
import shlex

from sourcedock.core.models import SOURCE_APT
from sourcedock.core.process import redact_text



EMPTY_VALUE = "—"


def _value(value: str) -> str:
    return value.strip() if value and value.strip() else EMPTY_VALUE


def _parse_apt_list_line(line: str, filename: str):
    try:
        tokens = shlex.split(line, comments=False)
    except ValueError:
        return None
    if len(tokens) < 3 or tokens[0] not in {"deb", "deb-src"}:
        return None
    index = 1
    options = []
    if index < len(tokens) and tokens[index].startswith("["):
        while index < len(tokens):
            options.append(tokens[index])
            if tokens[index].endswith("]"):
                index += 1
                break
            index += 1
    if len(tokens) <= index + 1:
        return None
    uri = tokens[index]
    suite = tokens[index + 1]
    components = tokens[index + 2:]
    channel = " ".join(part for part in (suite, *components) if part)
    if options:
        channel = f"{' '.join(options)} · {channel}"
    if tokens[0] == "deb-src":
        channel = f"source · {channel}"
    return ("APT", filename, redact_text(uri), _value(channel))


def _parse_apt_sources_stanza(stanza, filename: str):
    fields = Parser().parsestr(stanza)
    uris = fields.get("URIs", "").split()
    if not uris:
        return []
    types = fields.get("Types", "")
    suites = fields.get("Suites", "")
    components = fields.get("Components", "")
    architectures = fields.get("Architectures", "")
    enabled = fields.get("Enabled", "")
    channel = " ".join(part for part in (types, suites, components) if part)
    if architectures:
        channel = f"{channel} · arch={architectures}" if channel else f"arch={architectures}"
    if enabled:
        channel = f"{channel} · enabled={enabled}" if channel else f"enabled={enabled}"
    channel = _value(channel)
    return [("APT", filename, redact_text(uri), channel) for uri in uris]


def list_sources(runner, native_source):
    rows = []
    if native_source == SOURCE_APT:
        paths = [
            Path("/etc/apt/sources.list"),
            *Path("/etc/apt/sources.list.d").glob("*.list"),
            *Path("/etc/apt/sources.list.d").glob("*.sources"),
        ]
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if path.suffix == ".sources":
                for stanza in content.split("\n\n"):
                    rows.extend(_parse_apt_sources_stanza(stanza, path.name))
            else:
                for line in content.splitlines():
                    parsed = _parse_apt_list_line(line.strip(), path.name)
                    if parsed:
                        rows.append(parsed)
    elif runner.command_exists(native_source):
        commands = {
            "dnf": ["dnf", "repolist"],
            "zypper": ["zypper", "repos", "--uri"],
            "pacman": ["pacman-conf", "--repo-list"],
        }
        if native_source in commands:
            result = runner.run(commands[native_source], timeout=20)
            rows.extend(
                (native_source.upper(), EMPTY_VALUE, redact_text(line), EMPTY_VALUE)
                for line in result.stdout.splitlines()
                if line.strip()
            )
    if runner.command_exists("flatpak"):
        for scope in ("--user", "--system"):
            result = runner.run(["flatpak", "remotes", scope, "--columns=name,url"], timeout=15)
            for line in result.stdout.splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    rows.append(("Flatpak", parts[0], redact_text(parts[1]), scope.removeprefix("--")))
    if runner.command_exists("snap"):
        result = runner.run(["snap", "list"], timeout=15)
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                rows.append(("Snap", parts[0], "snap-store", parts[3]))
    return rows


REMOTE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")



def validate_remote_name(name: str) -> bool:
    """Validate remote name against unsafe characters and injection."""
    return bool(name and REMOTE_NAME_PATTERN.match(name.strip()))


def validate_remote_url(url: str) -> bool:
    """Validate remote URL (must be http/https/file URI with no shell meta)."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not (u.startswith("https://") or u.startswith("http://") or u.startswith("file://")):
        return False
    if any(char in u for char in (" ", "\t", "\n", "\r", ";", "&", "|", "`", "$", "'", '"', "<", ">")):
        return False
    return True


def add_flatpak_remote(runner, name: str, url: str, user: bool = True) -> tuple[bool, str]:
    """Add a Flatpak remote with strict input validation and argv list execution."""
    clean_name = (name or "").strip()
    clean_url = (url or "").strip()
    if not validate_remote_name(clean_name):
        return False, "invalid_name"
    if not validate_remote_url(clean_url):
        return False, "invalid_url"
    if not runner.command_exists("flatpak"):
        return False, "flatpak_not_available"

    cmd = ["flatpak", "remote-add", "--if-not-exists"]
    if user:
        cmd.append("--user")
    else:
        cmd.append("--system")
    cmd.extend([clean_name, clean_url])

    result = runner.run(cmd, timeout=30)
    if result.exit_code == 0:
        return True, ""
    return False, result.stderr or result.stdout


def remove_flatpak_remote(runner, name: str, user: bool = True) -> tuple[bool, str]:
    """Remove a Flatpak remote safely."""
    clean_name = (name or "").strip()
    if not validate_remote_name(clean_name):
        return False, "invalid_name"
    if not runner.command_exists("flatpak"):
        return False, "flatpak_not_available"

    cmd = ["flatpak", "remote-delete", "--force"]
    if user:
        cmd.append("--user")
    else:
        cmd.append("--system")
    cmd.append(clean_name)

    result = runner.run(cmd, timeout=30)
    if result.exit_code == 0:
        return True, ""
    return False, result.stderr or result.stdout

