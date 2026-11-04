"""Install-first source changes: failed verification never removes the old copy."""

from dataclasses import dataclass

from sourcedock.core.app_identity import installation_key, matching_installations, SWITCHABLE_SOURCES
from sourcedock.core.errors import BackendError
from sourcedock.core.models import StoreResult, UnifiedApplication, is_native_source
from sourcedock.core.transactions import transaction_scope


@dataclass(frozen=True)
class SourceSwitchPlan:
    target: StoreResult
    previous: UnifiedApplication
    variants: tuple[StoreResult, ...] = ()


def verify_destination(registry, target):
    if not target.is_application or target.source not in SWITCHABLE_SOURCES:
        raise BackendError("This item does not support changing application sources.")
    snapshot = registry.load_sources({target.source})
    if snapshot.provider_errors:
        raise BackendError("Destination inventory could not be verified.")
    for application in snapshot.applications:
        package = installation_key(application)[1]
        expected = target.app_id.split(":", 1)[0] if is_native_source(target.source) else target.app_id
        if (application.source == target.source and package == expected
                and application.desktop_file):
            return application
    raise BackendError("The destination application is not present in the installed inventory.")


def remove_previous_after_install(registry, plan):
    if (plan.previous.source == plan.target.source
            or not matching_installations(plan.target, [plan.previous], plan.variants)):
        raise BackendError("The selected packages are not verified alternatives of the same application.")
    # This short second stage touches two databases. Keep all package mutations
    # outside the verify/remove interval, including operations from other runners.
    # Read-only browsing remains available throughout.
    runner = registry.runner

    def waiting():
        callback = runner._resolve_output_callback()
        if callback:
            callback("SOURCEDOCK_PHASE queued")

    with transaction_scope(["sourcedock-source-switch"], on_wait=waiting,
                           cancelled=runner._check_task_cancelled):
        runner._check_task_cancelled()
        runner._wait_for_critical_transactions()
        verify_destination(registry, plan.target)
        snapshot = registry.load_sources({plan.previous.source})
        if snapshot.provider_errors:
            raise BackendError("The previous installation could not be verified.")
        current = next((app for app in snapshot.applications
                        if installation_key(app) == installation_key(plan.previous)), None)
        if current is not None:
            registry.remove(current, purge=False)
