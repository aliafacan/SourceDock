"""Regression tests for APT installation dates after reinstallations."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import gzip
from pathlib import Path
import tempfile

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

    def test_multiple_upgrades_never_replace_installation_date(self):
        installed, updated = _parse_dpkg_history_lines([
            "2026-01-01 10:00:00 install demo:amd64 <none> 1.0",
            "2026-01-03 10:00:00 upgrade demo:amd64 1.0 1.1",
            "2026-01-05 10:00:00 upgrade demo:amd64 1.1 1.2",
        ])
        self.assertEqual(installed["demo:amd64"], "2026-01-01")
        self.assertEqual(updated["demo:amd64"], "2026-01-05")

    def test_upgrade_after_reinstall_uses_new_installation_instance(self):
        installed, updated = _parse_dpkg_history_lines([
            "2026-01-01 10:00:00 install demo:amd64 <none> 1.0",
            "2026-02-01 10:00:00 purge demo:amd64 1.0 <none>",
            "2026-03-01 10:00:00 install demo:amd64 <none> 2.0",
            "2026-03-02 10:00:00 upgrade demo:amd64 2.0 2.1",
        ])
        self.assertEqual(installed["demo:amd64"], "2026-03-01")
        self.assertEqual(updated["demo:amd64"], "2026-03-02")

    def test_missing_install_log_stays_unknown_when_upgrade_is_known(self):
        installed, updated = _parse_dpkg_history_lines([
            "2026-03-02 10:00:00 upgrade demo:amd64 2.0 2.1",
        ])
        self.assertNotIn("demo:amd64", installed)
        self.assertEqual(updated["demo:amd64"], "2026-03-02")

    def test_multiarch_installation_dates_are_independent(self):
        installed, updated = _parse_dpkg_history_lines([
            "2026-01-01 10:00:00 install libdemo:amd64 <none> 1.0",
            "2026-01-02 10:00:00 install libdemo:i386 <none> 1.0",
            "2026-01-04 10:00:00 upgrade libdemo:i386 1.0 1.1",
        ])
        self.assertEqual(installed["libdemo:amd64"], "2026-01-01")
        self.assertEqual(installed["libdemo:i386"], "2026-01-02")
        self.assertEqual(updated["libdemo:i386"], "2026-01-04")
        self.assertNotIn("libdemo", installed)

    def test_rotated_compressed_logs_are_read_chronologically(self):
        provider = AptProvider(MagicMock(), MagicMock())
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "dpkg.log"
            rotated = Path(directory) / "dpkg.log.1.gz"
            current.write_text(
                "2026-02-01 10:00:00 upgrade demo:amd64 1.0 2.0\n", encoding="utf-8"
            )
            with gzip.open(rotated, "wt", encoding="utf-8") as log:
                log.write("2026-01-01 10:00:00 install demo:amd64 <none> 1.0\n")
            with patch("sourcedock.backend.apt.glob.glob", return_value=[str(current), str(rotated)]):
                installed, updated = provider._parse_dpkg_history()
        self.assertEqual(installed["demo"], "2026-01-01")
        self.assertEqual(updated["demo"], "2026-02-01")

    def test_list_mtime_is_never_used_when_history_is_missing(self):
        provider = AptProvider(MagicMock(), MagicMock())
        provider._parse_dpkg_history = MagicMock(return_value=({}, {"demo": "2026-03-12"}))
        installed, updated = provider._collect_package_dates(["demo"])
        self.assertEqual(installed["demo"], "")
        self.assertEqual(updated["demo"], "2026-03-12")
        provider.runner.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
