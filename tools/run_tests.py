#!/usr/bin/env python3
"""Run trusted unit tests with isolated data and a host-command accident guard."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.test_guard import TestCommandGuard


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Optional dotted unittest names")
    parser.add_argument("--require-wm", action="store_true", help="Fail if an X11 window manager is missing")
    args = parser.parse_args()
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix="sourcedock-tests-") as directory:
        root = Path(directory)
        os.environ["GSETTINGS_BACKEND"] = "memory"
        os.environ["NO_AT_BRIDGE"] = "1"
        os.environ["SOURCEDOCK_DISABLE_RELEASE_CHECK"] = "1"
        os.environ["TMPDIR"] = directory
        tempfile.tempdir = directory
        for variable, name in (
            ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
        ):
            path = root / name
            path.mkdir()
            os.environ[variable] = str(path)
        guard = TestCommandGuard(root)
        sys.addaudithook(guard.audit)
        if args.require_wm:
            for _ in range(50):
                try:
                    wm = subprocess.run(
                        ["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                        capture_output=True, text=True, timeout=2,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"BLOCKED: window-manager probe failed: {exc}", file=sys.stderr)
                    return 2
                if wm.returncode == 0 and "window id # 0x" in wm.stdout:
                    break
                time.sleep(0.1)
            else:
                print("BLOCKED: an isolated X11 window manager is required.", file=sys.stderr)
                return 2
        loader = unittest.TestLoader()
        suite = (
            loader.loadTestsFromNames(args.tests) if args.tests
            else loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        )
        print("Host-command guard active; test data isolated in a temporary directory.", flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(f"Guard: {len(guard.allowed)} allowed command calls, {len(guard.blocked)} blocked attempts.")
        return 0 if result.wasSuccessful() and not guard.blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
