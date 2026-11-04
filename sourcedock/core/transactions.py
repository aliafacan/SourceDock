"""Coordinate mutations by package database, including nested authorization."""

from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import threading


_condition = threading.Condition(threading.RLock())
_owners = {}
_local = threading.local()


def command_resource(command):
    groups = {
        "apt": "apt", "apt-get": "apt", "dpkg": "apt", "nala": "apt",
        "dnf": "rpm", "rpm": "rpm", "zypper": "rpm", "pacman": "pacman",
        "snap": "snap", "flatpak": "flatpak", "fwupdmgr": "firmware",
        "AppImageUpdate": "appimage",
        "sourcedock-portable": "portable", "sourcedock-appimage": "appimage",
    }
    for arg in command[:6]:
        resource = groups.get(Path(arg).name)
        if resource:
            return resource
    return current_resource() or "global"


def current_resource():
    return getattr(_local, "resource", None)


def resources_conflict(left, right):
    return left == right or "global" in (left, right)


def serialized_resource(resource):
    def decorate(function):
        @wraps(function)
        def serialized(*args, **kwargs):
            with transaction_scope([resource]):
                return function(*args, **kwargs)
        return serialized
    return decorate


@contextmanager
def transaction_scope(command, on_wait=None, cancelled=None):
    resource = command_resource(command)
    previous = current_resource()
    if previous:
        # sudo probes and streaming calls belong to the outer transaction.
        yield previous
        return
    owner = threading.get_ident()
    with _condition:
        notified = False
        while any(resources_conflict(resource, other) for other in _owners.values()):
            if not notified and on_wait:
                on_wait()
                notified = True
            if cancelled:
                cancelled()
            _condition.wait(0.2)
        _owners[owner] = resource
        _local.resource = resource
    try:
        yield resource
    finally:
        with _condition:
            _owners.pop(owner, None)
            _local.resource = previous
            _condition.notify_all()
