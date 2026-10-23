#!/usr/bin/env bash
# Run the read-only GTK acceptance matrix on isolated Xvfb roots.
# This script never installs packages and writes evidence under /tmp by default.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_ROOT="${SOURCEDOCK_X11_OUTPUT:-$(mktemp -d "${TMPDIR:-/tmp}/sourcedock-x11-acceptance-XXXXXXXX")}"

if ! command -v Xvfb >/dev/null 2>&1; then
    echo "BLOCKED: Xvfb is missing. Install xvfb with user approval." >&2
    exit 2
fi
if ! command -v openbox >/dev/null 2>&1; then
    echo "BLOCKED: openbox is missing. Install a lightweight WM with user approval." >&2
    exit 2
fi
for tool in xdpyinfo xprop setsid python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "BLOCKED: required tool $tool is missing." >&2
        exit 2
    fi
done

mkdir -p "$OUTPUT_ROOT"
pids=()

cleanup() {
    local pid
    # Only signal process groups created by this runner; never touch another display.
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    for _ in {1..20}; do
        local alive=0
        for pid in "${pids[@]}"; do
            if kill -0 -- "-$pid" 2>/dev/null; then alive=1; fi
        done
        if [ "$alive" -eq 0 ]; then break; fi
        sleep 0.05
    done
    for pid in "${pids[@]}"; do
        kill -KILL -- "-$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    pids=()
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

SOURCEDOCK_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
if [[ "$SOURCEDOCK_DATA_HOME" == */snap/* ]]; then
    SOURCEDOCK_DATA_HOME="$HOME/.local/share"
fi

CLEAN_ENV=(env \
        -u LD_LIBRARY_PATH \
        -u LD_PRELOAD \
        -u GTK_PATH \
        -u GTK_THEME \
        -u GTK_MODULES \
        -u GTK_EXE_PREFIX \
        -u GTK3_MODULES \
        -u GTK_IM_MODULE \
        -u GTK_IM_MODULE_FILE \
        -u GDK_PIXBUF_MODULEDIR \
        -u GDK_PIXBUF_MODULE_FILE \
        -u GIO_MODULE_DIR \
        -u GIO_EXTRA_MODULES \
        -u GSETTINGS_SCHEMA_DIR \
        -u LOCPATH \
        -u SNAP \
        -u SNAP_LIBRARY_PATH \
        -u DBUS_SESSION_BUS_ADDRESS \
        -u SESSION_MANAGER \
        -u XDG_CONFIG_DIRS_VSCODE_SNAP_ORIG \
        -u XDG_DATA_DIRS_VSCODE_SNAP_ORIG \
        GDK_BACKEND=x11 \
        GDK_SCALE=1 \
        GDK_DPI_SCALE=1 \
        GSETTINGS_BACKEND=memory \
        NO_AT_BRIDGE=1 \
        XDG_DATA_HOME="$SOURCEDOCK_DATA_HOME" \
        XDG_DATA_DIRS=/usr/share/zorin:/usr/share/gnome:/usr/local/share:/usr/share:/var/lib/snapd/desktop)

result=0
for spec in 1024x768 1366x768; do
    output="$OUTPUT_ROOT/$spec"
    if ! mkdir "$output"; then
        echo "Refusing to overwrite existing evidence: $output" >&2
        exit 2
    fi
    mkdir -m 700 "$output/runtime" "$output/config" "$output/cache"
    export XDG_RUNTIME_DIR="$output/runtime"
    export XDG_CONFIG_HOME="$output/config"
    export XDG_CACHE_HOME="$output/cache"

    echo "Starting isolated X11 root ($spec)"
    # -displayfd atomically reserves a free display and writes its number when ready.
    "${CLEAN_ENV[@]}" setsid Xvfb -displayfd 3 -screen 0 "${spec}x24" -ac +extension RANDR -nolisten tcp \
        3>"$output/display-number" >"$output/xvfb.log" 2>&1 &
    x_pid=$!
    pids+=("$x_pid")
    for _ in {1..100}; do
        if [ -s "$output/display-number" ]; then break; fi
        if ! kill -0 "$x_pid" 2>/dev/null; then break; fi
        sleep 0.1
    done
    display_number="$(<"$output/display-number")"
    if [[ ! "$display_number" =~ ^[0-9]+$ ]] || ! kill -0 "$x_pid" 2>/dev/null; then
        echo "BLOCKED: isolated Xvfb did not start; see $output/xvfb.log" >&2
        exit 2
    fi
    export DISPLAY=":$display_number"
    "${CLEAN_ENV[@]}" xdpyinfo >"$output/xdpyinfo.txt"

    "${CLEAN_ENV[@]}" setsid openbox --sm-disable >"$output/openbox.log" 2>&1 &
    wm_pid=$!
    pids+=("$wm_pid")
    wm_ready=0
    for _ in {1..100}; do
        if ! kill -0 "$wm_pid" 2>/dev/null; then break; fi
        if "${CLEAN_ENV[@]}" xprop -root _NET_SUPPORTING_WM_CHECK 2>/dev/null | grep -q 'window id # 0x'; then
            wm_ready=1
            break
        fi
        sleep 0.1
    done
    if [ "$wm_ready" -ne 1 ]; then
        echo "BLOCKED: Openbox did not manage the isolated display; see $output/openbox.log" >&2
        exit 2
    fi
    "${CLEAN_ENV[@]}" xprop -root _NET_WORKAREA _NET_SUPPORTING_WM_CHECK >"$output/workarea.txt"

    package_args=()
    package="${SOURCEDOCK_TEST_PACKAGE:-$ROOT/packaging/sourcedock_1.4.0_all.deb}"
    if [ -f "$package" ]; then package_args=(--package "$package"); fi
    "${CLEAN_ENV[@]}" setsid python3 "$ROOT/tools/ui_smoke.py" \
        --real-data --matrix --root-fit --expected-root "$spec" --output "$output" \
        "${package_args[@]}" "$@" >"$output/smoke.log" 2>&1 &
    smoke_pid=$!
    pids+=("$smoke_pid")
    smoke_status=0
    wait "$smoke_pid" || smoke_status=$?
    cat "$output/smoke.log"
    # Independently check the measured bounds and PNG dimensions, not just clipped_controls.
    if ! "${CLEAN_ENV[@]}" python3 - "$output" "$spec" >"$output/runner-validation.json" <<'PY'
import json
from pathlib import Path
import struct
import sys

output = Path(sys.argv[1])
expected = [int(value) for value in sys.argv[2].split("x")]
errors = []

def inside(rect, bounds):
    x, y, width, height = rect
    bx, by, bw, bh = bounds
    return width > 0 and height > 0 and x >= bx and y >= by and x + width <= bx + bw and y + height <= by + bh

def check_geometry(label, geometry):
    if geometry["root_screen"] != expected:
        errors.append(f"{label}: wrong root screen")
    if not inside(geometry["outer_frame"], [0, 0, *expected]) or not inside(geometry["outer_frame"], geometry["workarea"]):
        errors.append(f"{label}: outer frame outside root/workarea")
    for name, control in geometry["action_controls"].items():
        if control["mapped"] and not control.get("scrollable"):
            if not control.get("measurable") or not control.get("in_window") or not inside(control["root_rect"], geometry["workarea"]):
                errors.append(f"{label}: {name} outside visible bounds")

def png_size(name):
    with (output / name).open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"Not a PNG: {name}")
    return list(struct.unpack(">II", header[16:24]))

def check_capture(label, evidence):
    if evidence["source"] != "x11-root-pixels" or not evidence["complete_outer_frame"]:
        errors.append(f"{label}: incomplete outer-frame proof")
    if png_size(evidence["file"]) != evidence["outer_frame"][2:]:
        errors.append(f"{label}: outer-frame PNG size mismatch")
    if png_size(evidence["root_file"]) != expected or evidence["root_pixel_size"] != expected:
        errors.append(f"{label}: root PNG size mismatch")

try:
    data = json.loads((output / "validation.json").read_text())
    if not data["root_fit"] or not data["cases"]:
        errors.append("Root-fit cases missing")
    for index, case in enumerate(data["cases"]):
        label = f"case {index}"
        if case["requested"] != expected or case["status"] != "PASS" or case["clipped_controls"] or case["failures"]:
            errors.append(f"{label}: case failed or wrong requested size")
        if case["harness_fit"]["status"] != "PASS":
            errors.append(f"{label}: outer fitting failed")
        check_geometry(f"{label} natural", case["natural_geometry"])
        check_capture(f"{label} natural", case["natural_capture"])
        for page, geometry in case["geometry_by_page"].items():
            check_geometry(f"{label} {page}", geometry)
            check_capture(f"{label} {page}", case["captures"][page])
        for name in ("settings", "details", "installer"):
            dialog = case["dialogs"][name]
            if dialog["status"] == "NOT TESTED":
                errors.append(f"{label} {name}: NOT TESTED ({dialog['reason']})")
                continue
            if dialog["status"] != "PASS" or dialog["harness_adjusted"]:
                errors.append(f"{label} {name}: dialog failed or adjusted by harness")
            check_geometry(f"{label} {name}", dialog["natural_geometry"])
            check_capture(f"{label} {name}", dialog["capture"])
    if data["status"] != "PASS" or data["not_tested"]:
        errors.append("Acceptance contains failed or untested surfaces")
except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
    errors.append(str(error))

print(json.dumps({"status": "FAIL" if errors else "PASS", "expected_root": expected, "errors": errors}, indent=2))
sys.exit(bool(errors))
PY
    then
        result=1
    fi
    cat "$output/runner-validation.json"
    if [ "$smoke_status" -ne 0 ]; then result=1; fi
    cleanup
done

if [ "$result" -eq 0 ]; then
    echo "PASS: outer frames, visible controls and root PNGs verified under $OUTPUT_ROOT"
else
    echo "FAIL: inspect geometry and logs under $OUTPUT_ROOT" >&2
fi
exit "$result"
