"""Regression tests for APT installation dates after reinstallations."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.apt import AptProvider, _parse_dpkg_history_lines


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

    def test_install_event_with_old_and_new_versions_is_an_upgrade(self):
        lines = [
            "2026-04-01 10:00:00 install demo:amd64 <none> 1.0",
            "2026-04-12 10:00:00 install demo:amd64 1.0 1.1",
        ]

        installed, updated = _parse_dpkg_history_lines(lines)

        self.assertEqual(installed["demo"], "2026-04-01")
        self.assertEqual(updated["demo"], "2026-04-12")

    def test_collection_prefers_dpkg_upgrade_date_over_list_mtime(self):
        provider = AptProvider(MagicMock(), MagicMock())
        provider._parse_dpkg_history = MagicMock(
            return_value=({"demo": "2026-03-01"}, {"demo": "2026-03-12"})
        )
        provider._get_system_install_date = MagicMock(return_value="")
        stat_result = MagicMock(stdout="/var/lib/dpkg/info/demo.list\t1775000000\n")
        with patch.object(provider.runner, "run", return_value=stat_result):
            installed, updated = provider._collect_package_dates(["demo"])

        self.assertEqual(installed["demo"], "2026-03-01")
        self.assertEqual(updated["demo"], "2026-03-12")


if __name__ == "__main__":
    unittest.main()
