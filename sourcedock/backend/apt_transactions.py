"""APT package-level evidence and read-only rollback previews.

No rollback execution is exposed: a simulation cannot reserve the dpkg state
against external package managers. Never infer that a downgrade is safe merely
because apt can find an old version.
"""
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import uuid

from sourcedock.core.errors import BackendError
from sourcedock.core.json_store import write_json
from sourcedock.core.process import redact_text

PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?\Z")
VERSION = re.compile(r"[0-9][A-Za-z0-9.+:~\-]*\Z")


@dataclass(frozen=True)
class PackageState:
    version: str
    architecture: str
    automatic: bool
    essential: bool
    priority: str
    status: str


def snapshot(runner):
    result = runner.run_read_only([
        "dpkg-query", "-W",
        "-f=${Package}:${Architecture}\\t${Version}\\t${Architecture}\\t${Essential}\\t${Priority}\\t${db:Status-Status}\\n",
    ], timeout=30, check=True)
    marks = runner.run_read_only(["apt-mark", "showauto"], timeout=30, check=True)
    automatic = set(marks.stdout.splitlines())
    packages = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 6 or not PACKAGE.fullmatch(fields[0]):
            raise BackendError("Cannot verify dpkg state.")
        name, version, arch, essential, priority, status = fields
        if status == "not-installed":
            continue
        if status not in ("installed", "config-files"):
            raise BackendError("Package database needs recovery before rollback can be evaluated.")
        packages[name] = PackageState(version, arch, name in automatic or name.split(":")[0] in automatic,
                                      essential == "yes", priority, status)
    if not packages:
        raise BackendError("Empty package inventory cannot establish a rollback baseline.")
    return packages


def changes(before, after):
    return {name: (before.get(name), after.get(name)) for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)}


@dataclass
class AptTransaction:
    id: str
    command: list[str]
    before: dict[str, PackageState] = field(default_factory=dict)
    after: dict[str, PackageState] | None = None
    simulation: str = ""
    error: str = ""
    returncode: int | None = None
    log: str = ""

    @classmethod
    def begin(cls, runner, command, op_id=None):
        record = cls(op_id or uuid.uuid4().hex, list(command))
        try:
            record.before = snapshot(runner)
            result = runner.run_read_only(
                [command[0], "--simulate", "-o", "Debug::NoLocking=true", *command[1:]],
                timeout=45, check=True)
            record.simulation = redact_text(result.stdout)[-128000:]
        except BackendError as exc:
            record.error = redact_text(str(exc))
        record.save()
        return record

    def finish(self, runner, result):
        self.returncode = result.returncode
        self.log = redact_text((result.stdout or "") + (result.stderr or ""))[-128000:]
        try:
            self.after = snapshot(runner)
        except BackendError as exc:
            self.error = redact_text(str(exc))
        self.save()

    def save(self):
        # IDs are generated internally but validate before constructing paths.
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", self.id):
            raise BackendError("Invalid transaction identifier.")
        root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sourcedock" / "transactions"
        write_json(root / f"{self.id}.json", asdict(self))
        records = sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in records[50:]:
            path.unlink()

    def preview(self, runner):
        """Return evidence only; never return an executable rollback capability."""
        if self.error or not self.before or self.after is None:
            raise BackendError(self.error or "No verified package state after this operation.")
        if runner.has_global_active_critical_operation() or runner._apt_lock_holders():
            raise BackendError("A package operation is still running.")
        if snapshot(runner) != self.after:
            raise BackendError("Package state changed since the operation. The preview is stale.")
        delta = changes(self.before, self.after)
        arguments = []
        lines = []
        for name, (old, new) in delta.items():
            lines.append(f"{name}: {old.version if old else '—'} → {new.version if new else '—'}")
            if old and old.status == "installed":
                if not VERSION.fullmatch(old.version):
                    raise BackendError("Invalid recorded package version.")
                policy = runner.run_read_only(["apt-cache", "show", f"{name}={old.version}"], timeout=20)
                if policy.returncode or f"Version: {old.version}" not in policy.stdout:
                    raise BackendError(f"Previous version is unavailable: {name}={old.version}")
                arguments.append(f"{name}={old.version}")
            elif new and new.status == "installed":
                if new.essential or new.priority in ("required", "important"):
                    raise BackendError(f"Refusing removal of a protected package: {name}")
                arguments.append(f"{name}-")
        if arguments:
            simulation = runner.run_read_only(
                ["apt-get", "--simulate", "-o", "Debug::NoLocking=true", "install", "--", *arguments],
                timeout=45, check=True)
            lines.extend(["", redact_text(simulation.stdout)])
        return "\n".join(lines)
