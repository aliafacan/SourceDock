"""Regression tests for APT installation dates after reinstallations."""

from __future__ import annotations

import unittest

from sourcedock.backend.apt import _parse_dpkg_history_lines


class TestAptInstallationDates(unittest.TestCase):
    def test_reinstall_uses_latest_install_date(self):
        lines = [
            "2026-01-01 10:00:00 install demo:amd64 1.0",
            "2026-01-05 10:00:00 upgrade demo:amd64 1.1",
            "2026-02-01 10:00:00 remove demo:amd64 1.1",
            "2026-02-10 10:00:00 install demo:amd64 2.0",
        ]

        installed, updated = _parse_dpkg_history_lines(lines)

        self.assertEqual(installed["demo"], "2026-02-10")
        self.assertEqual(updated["demo"], "2026-02-10")

    def test_upgrade_keeps_current_install_date(self):
        lines = [
            "2026-03-01 10:00:00 install demo:amd64 1.0",
            "2026-03-12 10:00:00 upgrade demo:amd64 1.1",
        ]

        installed, updated = _parse_dpkg_history_lines(lines)

        self.assertEqual(installed["demo"], "2026-03-01")
        self.assertEqual(updated["demo"], "2026-03-12")


if __name__ == "__main__":
    unittest.main()
