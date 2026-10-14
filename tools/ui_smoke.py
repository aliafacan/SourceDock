#!/usr/bin/env python3
"""Read-only GTK screenshots and layout checks using actual provider metadata."""

import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.models import ApplicationSnapshot, SOURCE_APT, UnifiedApplication
from sourcedock.preferences import AppPreferences
from sourcedock.store.registry import StoreRegistry
from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog
from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
from sourcedock.ui.window import MainWindow


def settle(milliseconds=250):
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def capture(window, path):
    settle()
    assert window.get_mapped(), "Window did not map"
    native = window.get_window()
    width, height = native.get_width(), native.get_height()
    x = y = 0
    if window.get_titlebar():
        x, y = window.get_titlebar().translate_coordinates(window, 0, 0)
        child = window.get_child()
        child_x, child_y = child.translate_coordinates(window, 0, 0)
        width = child.get_allocated_width()
        height = child_y + child.get_allocated_height() - y
    pixbuf = Gdk.pixbuf_get_from_window(native, x, y, width, height)
    assert pixbuf is not None and len(set(pixbuf.get_pixels()[::97])) > 16, "Blank window"
    pixbuf.savev(str(path), "png", [], [])
    return [width, height]


def visible_bounds(window):
    failures = []
    width, height = window.get_allocated_width(), window.get_allocated_height()
    for name in (
        "header_search",
        "header_updates_btn",
        "local_install_btn",
        "settings_btn",
        "help_btn",
        "applications_refresh_btn",
        "applications_action_remove_btn",
        "applications_bulk_remove_btn",
        "store_search_btn",
        "packages_remove_btn",
        "updates_apply_btn",
    ):
        widget = getattr(window, name)
        if not widget.get_mapped():
            continue
        coordinates = widget.translate_coordinates(window, 0, 0)
        allocation = widget.get_allocation()
        if coordinates and (
            coordinates[0] < 0
            or coordinates[1] < 0
            or coordinates[0] + allocation.width > width
            or coordinates[1] + allocation.height > height
        ):
            failures.append(name)
    return failures


def capture_settings(window, path):
    captured = []

    def inspect_dialog():
        for dialog in Gtk.Window.list_toplevels():
            if isinstance(dialog, Gtk.Dialog) and dialog.get_transient_for() is window:
                try:
                    captured.append(capture(dialog, path))
                finally:
                    dialog.response(Gtk.ResponseType.CANCEL)
                return False
        return True

    timer = GLib.timeout_add(200, inspect_dialog)
    window.on_open_settings(None)
    if not captured:
        GLib.source_remove(timer)
        raise AssertionError("Settings dialog did not render")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/screenshots")
    parser.add_argument("--real-data", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--package")
    arguments = parser.parse_args()
    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    assert Gtk.init_check()[0], "A GTK display is required (use Xvfb in CI)"

    registry = ApplicationRegistry()
    snapshot = ApplicationSnapshot([])
    packages, results = [], []
    if arguments.real_data:
        print("Reading actual application and package metadata (no installations).", flush=True)
        snapshot = registry.load()
        packages = registry.list_packages()
        results = StoreRegistry().search("firefox")
        print(
            f"Loaded {len(snapshot.applications)} applications, {len(packages)} packages, {len(results)} search results.",
            flush=True,
        )
    updates = build_update_catalog(snapshot.applications, packages, registry.native_provider.source)
    sizes = [(1024, 768), (1366, 768), (1920, 1080)] if arguments.matrix else [(1366, 768)]
    cases = []
    for theme in ("dark", "light"):
        for language in ("tr", "en"):
            for scale in ("90", "100", "110", "125") if arguments.matrix else ("100",):
                for width, height in sizes:
                    preferences = type(
                        "Preferences", (), {"load": lambda self: AppPreferences(language, theme, scale)}
                    )()
                    with (
                        patch.object(MainWindow, "reload_applications_async"),
                        patch.object(MainWindow, "reload_packages_async"),
                        patch.object(MainWindow, "_reload_updates_async"),
                        patch("sourcedock.ui.window.Gtk.main_quit"),
                    ):
                        window = MainWindow(preferences)
                        window.resize(width, height)
                        window._finish_applications_load(snapshot)
                        window._finish_packages_load(packages, None)
                        window.store_results = results
                        window._finish_store_search(results, None)
                        window._finish_updates_load(updates, snapshot.provider_errors, None)
                        window.show_all()
                        settle()
                        window.resize(width, height)
                        settle()
                        suffix = f"{theme}-{language}-{scale}-{width}x{height}"
                        dimensions = capture(window, output / f"installed-{suffix}.png")
                        failures = visible_bounds(window)
                        # Every page is visited to verify lazily activated controls.
                        for page, name in (
                            (1, "discover"),
                            (2, "packages"),
                            (3, "operations"),
                            (4, "updates"),
                        ):
                            window.pages.set_current_page(page)
                            settle(100)
                            failures.extend(visible_bounds(window))
                            if width == 1366 and scale == "100":
                                capture(window, output / f"{name}-{suffix}.png")
                        if snapshot.applications and width == 1366 and scale == "100":
                            dialog = InstalledAppDetailsDialog(
                                snapshot.applications[0], registry, language, parent=window
                            )
                            capture(dialog, output / f"details-{suffix}.png")
                            dialog.destroy()
                        if arguments.package and width == 1366 and scale == "100":
                            info = registry.inspect_local_package(arguments.package)
                            status = registry.get_local_package_status(info)
                            dialog = PackageInstallerDialog(
                                parent=window,
                                info=info,
                                language=language,
                                pkg_status=status,
                                registry=registry,
                            )
                            dialog.show_all()
                            capture(dialog, output / f"installer-{suffix}.png")
                            dialog.destroy()
                        if width == 1366 and scale == "100":
                            capture_settings(window, output / f"settings-{suffix}.png")
                        cases.append(
                            {
                                "requested": [width, height],
                                "actual": dimensions,
                                "theme": theme,
                                "language": language,
                                "scale": scale,
                                "clipped_controls": sorted(set(failures)),
                            }
                        )
                        print(f"{suffix}: actual={dimensions}, clipped={sorted(set(failures))}", flush=True)
                        window.destroy()
    preferences = type("Preferences", (), {"load": lambda self: AppPreferences("en", "dark")})()
    with patch.object(MainWindow, "reload_applications_async"), patch("sourcedock.ui.window.Gtk.main_quit"):
        benchmark = MainWindow(preferences)
        benchmark.hide()
        fixtures = [
            UnifiedApplication(
                f"apt:fixture-{index}",
                f"Performance fixture {index}",
                SOURCE_APT,
                package_name=f"fixture-{index}",
            )
            for index in range(1000)
        ]
        benchmark.applications = fixtures
        measurements = []
        for _ in range(3):
            started = time.perf_counter()
            benchmark._render_applications_list()
            measurements.append(round((time.perf_counter() - started) * 1000, 2))
        benchmark.destroy()
    (output / "validation.json").write_text(
        json.dumps(
            {
                "real_data": arguments.real_data,
                "applications": len(snapshot.applications),
                "packages": len(packages),
                "cases": cases,
                "performance_fixture_records": 1000,
                "render_ms": measurements,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Controlled 1000-record render benchmark: {measurements} ms", flush=True)
    if any(case["clipped_controls"] for case in cases):
        raise SystemExit("Layout verification failed; see validation.json")


if __name__ == "__main__":
    main()
