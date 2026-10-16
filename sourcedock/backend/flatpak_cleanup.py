"""Read-only unused-ref plans followed by explicitly scoped cleanup."""

from dataclasses import dataclass
import re

from sourcedock.core.errors import BackendError


@dataclass(frozen=True)
class CleanupRef:
    scope: str
    ref: str


def plan_cleanup(runner):
    if runner.host_bridge_available:
        raise BackendError("Flatpak cleanup preview requires access to the host installation.")
    try:
        import gi

        gi.require_version("Flatpak", "1.0")
        from gi.repository import Flatpak

        refs = []
        for scope, constructor in (("user", Flatpak.Installation.new_user), ("system", Flatpak.Installation.new_system)):
            installation = constructor(None)
            refs.extend(CleanupRef(scope, ref.format_ref()) for ref in installation.list_unused_refs(None, None))
        return tuple(sorted(set(refs), key=lambda item: (item.scope, item.ref)))
    except (ValueError, ImportError) as exc:
        raise BackendError("Flatpak cleanup preview requires gir1.2-flatpak-1.0.") from exc
    except Exception as exc:
        raise BackendError(f"Could not calculate the Flatpak cleanup plan: {exc}") from exc


def apply_cleanup(runner, plan):
    targets = tuple(plan)
    if not targets:
        return
    for item in targets:
        if item.scope not in ("user", "system") or not re.fullmatch(
            r"(?:app|runtime)/[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9_]+/[A-Za-z0-9][A-Za-z0-9._-]*", item.ref
        ):
            raise BackendError("Invalid Flatpak cleanup target.")
    current = set(plan_cleanup(runner))
    if not set(targets).issubset(current):
        raise BackendError("The Flatpak cleanup plan changed. Review a new plan before continuing.")
    for scope in ("user", "system"):
        refs = sorted({item.ref for item in targets if item.scope == scope})
        if refs:
            command = ["flatpak", "uninstall", f"--{scope}", "--no-related", "--noninteractive", "-y", "--", *refs]
            if scope == "system":
                runner.run_privileged(command, timeout=300)
            else:
                runner.run(command, timeout=300, check=True)
