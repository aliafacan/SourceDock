#!/usr/bin/env python3
"""Measure actual GTK list interactions with synthetic, provider-free data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from sourcedock.core.models import SOURCE_APT, SOURCE_FLATPAK, UnifiedApplication
from sourcedock.preferences import AppPreferences
from sourcedock.ui.window import MainWindow
from tools.performance_benchmark import summary
from tools.test_guard import TestCommandGuard

BUDGETS_MS = {"populate": 1000, "search": 350, "source_filter": 250, "category_filter": 250, "scroll": 50}


def fixtures(count: int) -> list[UnifiedApplication]:
    return [
        UnifiedApplication(
            id=f"fixture:{index}", name=f"Fixture App {index:04d}",
            source=SOURCE_APT if index % 2 == 0 else SOURCE_FLATPAK,
            package_name=f"fixture-{index:04d}", version="1.0",
            desktop_file=f"/nonexistent/sourcedock-fixture-{index}.desktop",
            category="Development" if index % 3 == 0 else "Utility",
            installed_size_kib=1024, installed_date="2026-01-01", last_updated="2026-01-01",
            icon="package-x-generic",
        )
        for index in range(count)
    ]


def wait_for(condition, timeout=3):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        context.iteration(False)
        if condition():
            return
        time.sleep(0.001)
    raise RuntimeError("GTK did not reach the expected visible state before the deadline")


def measure_paint(tree, action, expected):
    started = time.perf_counter()
    painted = []

    def on_draw(_tree, _cr):
        if expected() and not painted:
            painted.append((time.perf_counter() - started) * 1000)
        return False

    handler = tree.connect_after("draw", on_draw)
    try:
        action()
        handler_ms = (time.perf_counter() - started) * 1000
        tree.queue_draw()
        wait_for(lambda: bool(painted))
        return handler_ms, painted[0]
    finally:
        tree.disconnect(handler)


def run_case(records, iterations, scale):
    case_started = time.perf_counter()
    registry, store = MagicMock(), MagicMock()
    registry.native_provider.source = SOURCE_APT
    registry.native_provider.display_name = "APT"
    store.native_manager = SOURCE_APT
    store.provider_errors = []
    store.missing_sources = []
    preferences = MagicMock()
    preferences.load.return_value = AppPreferences("en", "light", scale)
    with (
        patch("sourcedock.ui.window.ApplicationRegistry", return_value=registry),
        patch("sourcedock.ui.window.StoreRegistry", return_value=store),
        patch.object(MainWindow, "reload_applications_async"),
        patch.object(MainWindow, "reload_packages_async"),
        patch.object(MainWindow, "_reload_updates_async"),
        patch.object(MainWindow, "_on_operations_refresh"),
        patch("sourcedock.ui.window.Gtk.main_quit"),
    ):
        window = MainWindow(preferences)
    data = fixtures(records)
    measurements = {name: {"handler": [], "paint": []} for name in BUDGETS_MS}
    try:
        window.pages.set_current_page(0)
        window.show_all()
        window.applications = data
        window._update_category_combo()
        window._render_applications_list()
        tree = window.applications_tree
        wait_for(lambda: tree.get_mapped() and tree.get_allocated_height() > 1)
        initial_ready_ms = (time.perf_counter() - case_started) * 1000
        print(f"Initial data/model setup: {initial_ready_ms:.1f} ms", flush=True)
        iteration_times = []

        def rows(count):
            return len(window.applications_store) == count

        def sample(name, action, expected, warmup):
            try:
                handler_ms, paint_ms = measure_paint(tree, action, expected)
            except RuntimeError as exc:
                visible = tree.get_visible_range()
                indices = [path.get_indices() for path in visible] if visible else []
                raise RuntimeError(f"{name}: {exc}; rows={len(window.applications_store)}, visible={indices}") from exc
            if warmup:
                print(f"Warmup {name}: handler={handler_ms:.1f} paint={paint_ms:.1f} ms", flush=True)
            if not warmup:
                measurements[name]["handler"].append(handler_ms)
                measurements[name]["paint"].append(paint_ms)

        search_count = sum("app 00" in item.name.lower() for item in data)
        flatpak_count = sum(item.source == SOURCE_FLATPAK for item in data)
        category_count = sum(item.category == "Development" for item in data)
        for iteration in range(iterations + 1):
            iteration_started = time.perf_counter()
            warmup = iteration == 0
            sample("populate", window._render_applications_list, lambda: rows(records), warmup)
            sample("search", lambda: window.header_search.set_text("app 00"), lambda: rows(search_count), warmup)
            measure_paint(tree, lambda: window.header_search.set_text(""), lambda: rows(records))
            sample("source_filter", lambda: window.application_filter_buttons[SOURCE_FLATPAK].set_active(True),
                   lambda: rows(flatpak_count), warmup)
            measure_paint(tree, lambda: window.application_filter_buttons["all"].set_active(True), lambda: rows(records))
            sample("category_filter", lambda: window.applications_category_combo.set_active_id("Development"),
                   lambda: rows(category_count), warmup)
            measure_paint(tree, lambda: window.applications_category_combo.set_active_id("__all__"), lambda: rows(records))
            adjustment = tree.get_vadjustment()
            def last_row_visible():
                visible = tree.get_visible_range()
                return visible is not None and visible[-1].get_indices()[0] == records - 1

            sample("scroll", lambda: tree.scroll_to_cell(Gtk.TreePath.new_from_indices([records - 1]), None, True, 1.0, 0.0),
                   last_row_visible, warmup)
            measure_paint(tree, lambda: adjustment.set_value(0), lambda: adjustment.get_value() < 1)
            iteration_times.append(round((time.perf_counter() - iteration_started) * 1000, 1))
            print(f"Iteration {iteration}: {iteration_times[-1]} ms (warmup={warmup})", flush=True)
        for method in (registry.runner.run, registry.runner.run_privileged, store.search):
            method.assert_not_called()
        operations = {
            name: {
                "handler_ms": summary(values["handler"]), "first_paint_ms": summary(values["paint"]),
                "p95_budget_ms": BUDGETS_MS[name],
                "status": "PASS" if summary(values["paint"])["p95_ms"] <= BUDGETS_MS[name] else "FAIL",
            }
            for name, values in measurements.items()
        }
        return {
            "initial_ready_ms": round(initial_ready_ms, 1),
            "warmup_total_ms": iteration_times[0],
            "iterations_total_ms": iteration_times[1:],
            "operations": operations,
        }
    finally:
        window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--records", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--scale", choices=("100", "125"), default="100")
    args = parser.parse_args()
    if args.records < 1000 or args.iterations < 5:
        parser.error("At least 1000 records and 5 measured iterations are required")
    if not Gtk.init_check()[0]:
        parser.exit(2, "BLOCKED: an isolated GTK display is required\n")
    output = Path(args.output).resolve()
    if output.exists():
        parser.error("Refusing to overwrite existing evidence")
    screen = Gdk.Screen.get_default()
    report = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": "synthetic; no installed-application data or provider queries",
        "records": args.records, "iterations": args.iterations, "warmup_iterations": 1,
        "root_screen": [screen.get_width(), screen.get_height()], "application_font_scale": args.scale,
        "limitations": "Software X11 first draw, not GPU FPS, hardware wheel latency or real provider latency.",
    }
    with tempfile.TemporaryDirectory(prefix="sourcedock-ui-performance-") as directory:
        root = Path(directory)
        for variable, name in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
            os.environ[variable] = str(root / name)
        guard = TestCommandGuard(root)
        sys.addaudithook(guard.audit)
        try:
            report.update(run_case(args.records, args.iterations, args.scale))
            report["status"] = "PASS" if all(case["status"] == "PASS" for case in report["operations"].values()) else "FAIL"
        except Exception as exc:
            report.update(status="FAIL", error=str(exc))
        report["guard_blocked_commands"] = guard.blocked
        if guard.blocked:
            report["status"] = "FAIL"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
