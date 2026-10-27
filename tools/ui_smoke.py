#!/usr/bin/env python3
"""Read-only GTK screenshots and layout checks using actual provider metadata."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
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


ROOT = Path(__file__).resolve().parents[1]


def capture_provenance(package_path: str | None, sizes=None, root_fit=False) -> dict:
    def git_value(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    package = Path(package_path).expanduser().resolve() if package_path else None
    package_version = ""
    if package and package.exists():
        try:
            package_version = subprocess.run(
                ["dpkg-deb", "-f", str(package), "Version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            package_version = ""
    display = Gdk.Display.get_default()
    screen = Gdk.Screen.get_default()
    display_name = display.get_name() if display is not None else ""
    root_screen = [screen.get_width(), screen.get_height()] if screen is not None else []
    primary = display.get_primary_monitor() if display is not None else None
    workarea_rect = primary.get_workarea() if primary is not None else None
    x11_root_verified = is_x11_display()
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT),
        "execution_mode": "source-tree",
        "git_commit": git_value("rev-parse", "HEAD"),
        "worktree_dirty": bool(git_value("status", "--porcelain")),
        "package_path": str(package) if package else "",
        "package_version": package_version,
        "physical_viewport": "X11_ROOT_DOĞRULANDI" if x11_root_verified else "DOĞRULANMADI",
        "physical_viewport_reason": (
            f"X11 root ekranı gerçek piksel olarak ölçüldü: {root_screen[0]}x{root_screen[1]} ({display_name}). "
            "Pencere, dış çerçeve ve çalışma alanı ayrı ölçülür; pencere boyutu kök ekran modunun kanıtı değildir."
            if x11_root_verified
            else "X11/Xvfb root ekranı ölçülemedi."
        ),
        "display_backend": "x11" if x11_root_verified else display_name,
        "x11_root_screen": root_screen,
        "x11_primary_workarea": _rect_values(workarea_rect) if workarea_rect else [],
        "requested_viewports": [list(size) for size in (sizes or [])],
        "root_fit": root_fit,
        "scale_mode": "application CSS scale; GDK scale factor must be 1 for physical root tests",
        "search_state": {
            "baseline_page": "installed",
            "baseline_query": "",
            "discover_query": "firefox",
            "packages_query": "",
            "updates_query": "",
            "operations_query": "",
        },
    }


def settle(milliseconds=250):
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def is_x11_display():
    display = Gdk.Display.get_default()
    return display is not None and display.__gtype__.name == "GdkX11Display"


def rect_inside(rect, bounds):
    x, y, width, height = rect
    bx, by, bw, bh = bounds
    return (
        width > 0 and height > 0 and x >= bx and y >= by
        and x + width <= bx + bw and y + height <= by + bh
    )


def intersect_rect(rect, bounds):
    x, y = max(rect[0], bounds[0]), max(rect[1], bounds[1])
    right = min(rect[0] + rect[2], bounds[0] + bounds[2])
    bottom = min(rect[1] + rect[3], bounds[1] + bounds[3])
    return [x, y, max(0, right - x), max(0, bottom - y)]


def fit_main_window_to_viewport(window, width, height, *, root_fit=False):
    """Fit the measured outer frame; Gtk.Window.get_size excludes the CSD header."""
    settle(120)
    geometry = measure_window_geometry(window, (width, height))
    workarea = geometry["workarea"] or [0, 0, width, height]
    target = [workarea[0], workarea[1], width, height]
    if root_fit:
        target[2] = min(width, workarea[2])
        target[3] = min(height, workarea[3])
    attempts = []
    for _ in range(6):
        frame = _rect_values(window.get_window().get_frame_extents())
        attempts.append(frame)
        if frame == target:
            break
        client = window.get_size()
        if frame[2:] != target[2:]:
            window.resize(
                max(1, client.width + target[2] - frame[2]),
                max(1, client.height + target[3] - frame[3]),
            )
        # Gtk.Window.move uses the visible CSD origin, not the shadow/frame origin.
        position = window.get_position()
        window.move(position.root_x + target[0] - frame[0], position.root_y + target[1] - frame[1])
        settle(120)
    final = _rect_values(window.get_window().get_frame_extents())
    return {"target_outer_frame": target, "attempts": attempts, "actual_outer_frame": final,
            "status": "PASS" if final == target else "FAIL"}


def _rect_values(rect):
    return [rect.x, rect.y, rect.width, rect.height]


MAIN_CONTROLS = (
    "header_search", "header_updates_btn", "local_install_btn", "settings_btn", "help_btn",
    "applications_refresh_btn", "applications_action_remove_btn", "applications_bulk_remove_btn",
    "store_search_btn", "packages_remove_btn", "updates_select_all_btn", "updates_apply_btn",
)


def control_geometry(window, widget, workarea):
    mapped = widget.get_mapped()
    position = widget.translate_coordinates(window, 0, 0)
    result = {"mapped": mapped, "visible": widget.get_visible()}
    if position is None:
        result["measurable"] = False
        return result
    native = window.get_window()
    origin = native.get_origin()
    allocation = widget.get_allocation()
    local = [position[0], position[1], allocation.width, allocation.height]
    root_rect = [origin.x + local[0], origin.y + local[1], local[2], local[3]]
    result.update({
        "measurable": True,
        "root_rect": root_rect,
        "in_window": rect_inside(local, [0, 0, window.get_allocated_width(), window.get_allocated_height()]),
        "in_workarea": bool(workarea) and rect_inside(root_rect, workarea),
        "in_root": rect_inside(root_rect, [0, 0, native.get_screen().get_width(), native.get_screen().get_height()]),
    })
    ancestor = widget.get_parent()
    scroll_clips = []
    while ancestor is not None and ancestor is not window:
        if isinstance(ancestor, (Gtk.Viewport, Gtk.ScrolledWindow)):
            scroll_position = ancestor.translate_coordinates(window, 0, 0)
            if scroll_position is not None:
                scroll_clips.append([
                    origin.x + scroll_position[0], origin.y + scroll_position[1],
                    ancestor.get_allocated_width(), ancestor.get_allocated_height(),
                ])
        ancestor = ancestor.get_parent()
    result["scrollable"] = bool(scroll_clips)
    result["requires_scroll"] = any(not rect_inside(root_rect, clip) for clip in scroll_clips)
    return result


def dialog_controls(window):
    def walk(widget):
        if isinstance(widget, (Gtk.Button, Gtk.ComboBox, Gtk.Entry)):
            yield widget
        elif isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                yield from walk(child)

    return {
        f"{index}:{widget.__class__.__name__}:{widget.get_label() if isinstance(widget, Gtk.Button) else widget.get_name()}": widget
        for index, widget in enumerate(walk(window))
    }


def measure_window_geometry(window, requested):
    display = Gdk.Display.get_default()
    native = window.get_window()
    screen = Gdk.Screen.get_default()
    monitor = display.get_monitor_at_window(native) if display and native else None
    workarea = monitor.get_workarea() if monitor else None
    frame = native.get_frame_extents() if native else None
    titlebar = window.get_titlebar()
    child = window.get_child()
    titlebar_rect = titlebar.get_allocation() if titlebar else None
    child_rect = child.get_allocation() if child else None
    workarea_values = _rect_values(workarea) if workarea else []
    widgets = dialog_controls(window) if isinstance(window, Gtk.Dialog) else {
        name: getattr(window, name) for name in MAIN_CONTROLS if hasattr(window, name)
    }
    if titlebar is not None:
        widgets["titlebar"] = titlebar
    if hasattr(window, "sidebar"):
        widgets["sidebar"] = window.sidebar
    actions = {name: control_geometry(window, widget, workarea_values) for name, widget in widgets.items()}
    outer = _rect_values(frame) if frame else [0, 0, native.get_width(), native.get_height()]
    client = window.get_size()
    content = [child_rect.x, child_rect.y, child_rect.width, child_rect.height] if child_rect else []
    sidebar = getattr(window, "sidebar", None)
    required_controls = [item for item in actions.values() if item["mapped"] and not item.get("scrollable")]
    return {
        "requested": list(requested),
        "outer_frame": outer,
        "client_window": [client.width, client.height],
        "native_surface": [native.get_width(), native.get_height()],
        "gdk_scale_factor": window.get_scale_factor(),
        "modal": window.get_modal(),
        "window_widget": _rect_values(window.get_allocation()),
        "titlebar": _rect_values(titlebar_rect) if titlebar_rect else [],
        "content": content,
        "sidebar": {
            "allocation": _rect_values(sidebar.get_allocation()),
            "compact": bool(window._compact_sidebar),
            "brand_visible": window.brand_label.get_visible(),
            "labels_visible": all(label.get_visible() for label in window.nav_labels.values()),
        } if sidebar is not None else {},
        "root_screen": [screen.get_width(), screen.get_height()] if screen else [],
        "workarea": workarea_values,
        "action_controls": actions,
        "overflow_flags": {
            "outer_exceeds_workarea": bool(
                workarea
                and (outer[2] > workarea.width or outer[3] > workarea.height)
            ),
            "outer_outside_workarea": bool(workarea) and not rect_inside(outer, workarea_values),
            "outer_outside_root": not rect_inside(outer, [0, 0, screen.get_width(), screen.get_height()]),
            "essential_action_outside_workarea": any(
                not item.get("in_workarea", False) for item in required_controls
            ),
            "visible_control_outside_window": any(not item.get("in_window", False) for item in required_controls),
            "unmeasurable_control": any(not item.get("measurable", False) for item in required_controls),
        },
    }


def capture(window, path, *, root_proof=False):
    window.present()
    settle()
    assert window.get_mapped(), "Window did not map"
    native = window.get_window()
    frame = _rect_values(native.get_frame_extents())
    root = native.get_screen().get_root_window()
    root_rect = [0, 0, root.get_width(), root.get_height()]
    source = root if is_x11_display() else native
    rect = intersect_rect(frame, root_rect) if is_x11_display() else [0, 0, native.get_width(), native.get_height()]
    assert rect[2] > 0 and rect[3] > 0, "Window is entirely outside the root screen"
    pixbuf = Gdk.pixbuf_get_from_window(source, *rect)
    assert pixbuf is not None and len(set(pixbuf.get_pixels()[::97])) > 16, "Blank window"
    pixbuf.savev(str(path), "png", [], [])
    evidence = {
        "file": path.name, "pixel_size": [pixbuf.get_width(), pixbuf.get_height()],
        "source": "x11-root-pixels" if is_x11_display() else "native-surface",
        "outer_frame": frame, "captured_rect": rect,
        "complete_outer_frame": is_x11_display() and rect == frame,
    }
    if root_proof:
        assert is_x11_display(), "Root pixel proof requires X11"
        root_path = path.with_name(f"{path.stem}-root.png")
        root_pixbuf = Gdk.pixbuf_get_from_window(root, *root_rect)
        assert root_pixbuf is not None, "Cannot capture X11 root pixels"
        root_pixbuf.savev(str(root_path), "png", [], [])
        evidence.update({"root_file": root_path.name,
                         "root_pixel_size": [root_pixbuf.get_width(), root_pixbuf.get_height()]})
    return evidence


def visible_bounds(window):
    geometry = measure_window_geometry(window, window.get_size())
    return [name for name, item in geometry["action_controls"].items()
            if item["mapped"] and not item.get("scrollable") and not item.get("in_window", False)]


def capture_dialog(dialog, path, requested, *, root_fit=False):
    settle()
    natural = measure_window_geometry(dialog, requested)
    # Observe dialogs as shipped. A harness height clamp would hide real overflow.
    screenshot = capture(dialog, path, root_proof=root_fit)
    return {"status": "FAIL" if geometry_failures(natural) else "PASS",
            "natural_geometry": natural, "harness_adjusted": False, "capture": screenshot}


def geometry_failures(geometry):
    return [name for name, failed in geometry["overflow_flags"].items() if failed]


def capture_settings(window, path, requested, *, root_fit=False):
    captured = []
    errors = []
    existing = set(Gtk.Window.list_toplevels())
    deadline = time.monotonic() + 8
    active = True

    def inspect_dialog():
        nonlocal active
        for dialog in Gtk.Window.list_toplevels():
            if isinstance(dialog, Gtk.Dialog) and dialog not in existing and dialog.get_mapped():
                try:
                    captured.append(capture_dialog(dialog, path, requested, root_fit=root_fit))
                except Exception as error:
                    errors.append(error)
                finally:
                    active = False
                    dialog.response(Gtk.ResponseType.CANCEL)
                return False
        if time.monotonic() >= deadline:
            active = False
            errors.append(AssertionError("Settings dialog did not render within 8 seconds"))
            for dialog in set(Gtk.Window.list_toplevels()) - existing:
                if isinstance(dialog, Gtk.Dialog):
                    dialog.response(Gtk.ResponseType.CANCEL)
            return False
        return True

    timer = GLib.timeout_add(100, inspect_dialog)
    try:
        window.on_open_settings(None)
    finally:
        if active:
            GLib.source_remove(timer)
    if errors:
        raise errors[0]
    assert captured, "Settings dialog did not render"
    return captured[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/screenshots")
    parser.add_argument("--real-data", action="store_true")
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--root-fit", action="store_true", help="Test only the actual X11 root size and enforce outer/control bounds")
    parser.add_argument("--expected-root", help="Require an exact physical X11 root, e.g. 1024x768")
    parser.add_argument("--themes", nargs="+", choices=("dark", "light", "system"))
    parser.add_argument(
        "--languages",
        nargs="+",
        choices=("tr", "en", "de", "es", "pt_BR", "fr"),
    )
    parser.add_argument("--scales", nargs="+", choices=("90", "100", "110", "125"))
    parser.add_argument("--package")
    arguments = parser.parse_args()
    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    assert Gtk.init_check()[0], "A GTK display is required (use Xvfb in CI)"
    screen = Gdk.Screen.get_default()
    root_size = (screen.get_width(), screen.get_height())
    if arguments.root_fit:
        assert is_x11_display(), "--root-fit requires an X11 display"
        assert screen.get_root_window().get_scale_factor() == 1, "Use GDK_SCALE=1 for physical root pixels"
    if arguments.expected_root:
        assert is_x11_display(), "--expected-root requires X11"
        assert arguments.expected_root == f"{root_size[0]}x{root_size[1]}", (
            f"Root mismatch: expected {arguments.expected_root}, measured {root_size}"
        )

    registry = ApplicationRegistry()
    snapshot = ApplicationSnapshot([])
    packages, results = [], []
    application_load_metrics = {}
    store_search_metrics = {}
    store_partial_events = []
    if arguments.real_data:
        print("Reading actual application and package metadata (no installations).", flush=True)
        load_started = time.perf_counter()
        progressive_events = []
        snapshot = registry.load_progressive(
            lambda current, complete: progressive_events.append(
                (round((time.perf_counter() - load_started) * 1000, 1), len(current.applications), complete)
            )
        )
        application_load_metrics = {
            "first_snapshot_ms": progressive_events[0][0] if progressive_events else None,
            "first_meaningful_ms": next(
                (event[0] for event in progressive_events if event[1] > 0), None
            ),
            "complete_ms": progressive_events[-1][0] if progressive_events else None,
            "snapshots": progressive_events,
            "provider_metrics": dict(registry.last_provider_metrics),
        }
        packages = registry.list_packages()
        store_registry = StoreRegistry()
        results = store_registry.search(
            "firefox",
            on_partial=lambda current, complete: store_partial_events.append(
                (len(current), complete)
            ),
        )
        store_search_metrics = store_registry.last_search_metrics
        print(
            f"Loaded {len(snapshot.applications)} applications, {len(packages)} packages, {len(results)} search results.",
            flush=True,
        )
    updates = build_update_catalog(snapshot.applications, packages, registry.native_provider.source)
    sizes = [(1024, 768), (1366, 768), (1920, 1080)] if arguments.matrix else [(1366, 768)]
    if arguments.root_fit:
        sizes = [root_size]
    cases = []
    for theme in arguments.themes or ("dark", "light", "system"):
        for language in arguments.languages or ("tr", "en"):
            for scale in arguments.scales or (("90", "100", "110", "125") if arguments.matrix else ("100",)):
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
                        window._suppress_store_search = True
                        window._finish_applications_load(snapshot)
                        window._finish_packages_load(packages, None)
                        window._suppress_store_search_changed = True
                        window.store_search_entry.set_text("firefox")
                        if window._store_search_timeout_id:
                            GLib.source_remove(window._store_search_timeout_id)
                            window._store_search_timeout_id = 0
                        window.store_results = results
                        window._finish_store_search(results, None)
                        window._finish_updates_load(
                            updates, snapshot.provider_errors + snapshot.provider_notices, None
                        )
                        # Baseline captures begin from an unfiltered Installed
                        # page; Discover's fixture query is restored only when
                        # that page is visited below.
                        window.applications_search_entry.set_text("")
                        window.application_search_text = ""
                        window.packages_search_entry.set_text("")
                        window.pages.set_current_page(0)
                        window._refresh_shell_page(0)
                        window.show_all()
                        if window._store_search_timeout_id:
                            GLib.source_remove(window._store_search_timeout_id)
                            window._store_search_timeout_id = 0
                        window._finish_store_search(results, None)
                        settle()
                        suffix = f"{theme}-{language}-{scale}-{width}x{height}"
                        natural_geometry = measure_window_geometry(window, (width, height))
                        natural_capture = (
                            capture(window, output / f"natural-{suffix}.png", root_proof=True)
                            if arguments.root_fit else None
                        )
                        fit_result = fit_main_window_to_viewport(window, width, height, root_fit=arguments.root_fit)
                        captures = {"installed": capture(window, output / f"installed-{suffix}.png", root_proof=arguments.root_fit)}
                        dimensions = captures["installed"]["pixel_size"]
                        geometry_by_page = {
                            "installed": measure_window_geometry(window, (width, height))
                        }
                        failures = visible_bounds(window)
                        # Release the Discover fixture only after the clean
                        # Installed baseline has been captured.
                        window._suppress_store_search_changed = False
                        # Every page is visited to verify lazily activated controls.
                        for page, name in (
                            (1, "discover"),
                            (2, "packages"),
                            (3, "operations"),
                            (4, "updates"),
                        ):
                            window.pages.set_current_page(page)
                            settle(100)
                            geometry_by_page[name] = measure_window_geometry(window, (width, height))
                            failures.extend(visible_bounds(window))
                            if arguments.root_fit or (width == 1366 and scale == "100"):
                                captures[name] = capture(window, output / f"{name}-{suffix}.png", root_proof=arguments.root_fit)
                        dialogs = {
                            "details": {"status": "NOT TESTED", "reason": "No installed application metadata or not selected in the legacy matrix"},
                            "installer": {"status": "NOT TESTED", "reason": "No --package supplied or not selected in the legacy matrix"},
                            "settings": {"status": "NOT TESTED", "reason": "Not selected in the legacy matrix"},
                        }
                        capture_dialogs = arguments.root_fit or (width == 1366 and scale == "100")
                        if snapshot.applications and capture_dialogs:
                            dialog = InstalledAppDetailsDialog(
                                snapshot.applications[0], registry, language, parent=window
                            )
                            try:
                                dialogs["details"] = capture_dialog(dialog, output / f"details-{suffix}.png", (width, height), root_fit=arguments.root_fit)
                            finally:
                                dialog.destroy()
                        if arguments.package and capture_dialogs:
                            info = registry.inspect_local_package(arguments.package)
                            status = registry.get_local_package_status(info)
                            dialog = PackageInstallerDialog(
                                parent=window,
                                info=info,
                                language=language,
                                pkg_status=status,
                                registry=registry,
                            )
                            try:
                                dialog.show_all()
                                dialogs["installer"] = capture_dialog(dialog, output / f"installer-{suffix}.png", (width, height), root_fit=arguments.root_fit)
                            finally:
                                dialog.destroy()
                        if capture_dialogs:
                            dialogs["settings"] = capture_settings(window, output / f"settings-{suffix}.png", (width, height), root_fit=arguments.root_fit)
                        errors = []
                        if arguments.root_fit:
                            # The natural window is measured before the viewport fit.
                            # On a 768px root, GTK's CSD frame can be a few pixels
                            # taller than the root; that diagnostic is not a failure
                            # once the harness fit succeeds.
                            if fit_result["status"] != "PASS":
                                errors.append("harness:outer_frame_does_not_match_target")
                            for page_name, geometry in geometry_by_page.items():
                                errors.extend(f"{page_name}:{name}" for name in geometry_failures(geometry))
                            for name, result in dialogs.items():
                                if result["status"] == "FAIL":
                                    errors.extend(f"{name}:{flag}" for flag in geometry_failures(result["natural_geometry"]))
                            for name, result in captures.items():
                                if not result["complete_outer_frame"]:
                                    errors.append(f"{name}:incomplete_outer_frame_capture")
                            for name, result in dialogs.items():
                                if "capture" in result and not result["capture"]["complete_outer_frame"]:
                                    errors.append(f"{name}:incomplete_outer_frame_capture")
                        cases.append(
                            {
                                "requested": [width, height],
                                "actual": dimensions,
                                "natural_geometry": natural_geometry,
                                "natural_capture": natural_capture,
                                "harness_fit": fit_result,
                                "geometry_by_page": geometry_by_page,
                                "captures": captures,
                                "dialogs": dialogs,
                                "theme": theme,
                                "language": language,
                                "scale": scale,
                                "clipped_controls": sorted(set(failures)),
                                "failures": errors,
                                "status": (
                                    "FAIL" if errors or failures else
                                    "NOT TESTED" if any(result["status"] == "NOT TESTED" for result in dialogs.values()) else
                                    "PASS"
                                ),
                            }
                        )
                        print(f"{suffix}: actual={dimensions}, clipped={sorted(set(failures))}, failures={errors}", flush=True)
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
                "application_load_metrics": application_load_metrics,
                "store_search_metrics": store_search_metrics,
                "store_partial_events": store_partial_events,
                "root_fit": arguments.root_fit,
                "status": (
                    "FAIL" if any(case["status"] == "FAIL" for case in cases) else
                    "NOT TESTED" if any(case["status"] == "NOT TESTED" for case in cases) else
                    "PASS"
                ),
                "provider_errors": snapshot.provider_errors,
                "provider_notices": snapshot.provider_notices,
                "not_tested": sorted({name for case in cases for name, result in case["dialogs"].items() if result["status"] == "NOT TESTED"}),
                "capture_provenance": capture_provenance(arguments.package, sizes, arguments.root_fit),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Controlled 1000-record render benchmark: {measurements} ms", flush=True)
    if any(case["status"] == "FAIL" for case in cases):
        raise SystemExit("Layout verification failed; see validation.json")
    if arguments.root_fit and any(case["status"] == "NOT TESTED" for case in cases):
        print("NOT TESTED: root acceptance has missing dialog metadata; see validation.json", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
