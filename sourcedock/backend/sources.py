"""Read configured sources without editing repositories or changing channels."""

from email.parser import Parser
from pathlib import Path

from sourcedock.core.models import SOURCE_APT
from sourcedock.core.process import redact_text


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
                    fields = Parser().parsestr(stanza)
                    if fields.get("URIs"):
                        rows.append(("APT", path.name, redact_text(fields["URIs"]), fields.get("Suites", "")))
            else:
                for line in content.splitlines():
                    if line.strip().startswith(("deb ", "deb-src ")):
                        rows.append(("APT", path.name, redact_text(line.strip()), ""))
    elif runner.command_exists(native_source):
        commands = {
            "dnf": ["dnf", "repolist"],
            "zypper": ["zypper", "repos", "--uri"],
            "pacman": ["pacman-conf", "--repo-list"],
        }
        if native_source in commands:
            result = runner.run(commands[native_source], timeout=20)
            rows.extend(
                (native_source.upper(), "", redact_text(line), "")
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
