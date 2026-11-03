"""v1.4.9 regressions for authoritative APT updates and exact store search."""

from __future__ import annotations

import subprocess
import threading
import unittest
from unittest.mock import MagicMock

from sourcedock.backend.apt import AptProvider, _parse_apt_upgradable_output
from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.errors import BackendError
from sourcedock.core.models import (
    PackageInfo, SOURCE_APT, SOURCE_FLATPAK, StoreResult, UnifiedApplication,
)
from sourcedock.store.registry import StoreRegistry


def completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestAptUpdateInventory149(unittest.TestCase):
    def provider(self, results):
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = results
        return AptProvider(runner, MagicMock())

    def test_six_updates_include_kernel_cli_library_and_third_party_packages(self):
        installed = "\n".join(
            f"{name}\t1.0\t10\t{description}\tinstalled"
            for name, description in (
                ("firefox", "browser"),
                ("linux-image-amd64", "kernel"),
                ("libssl3:amd64", "library"),
                ("winehq-stable", "WineHQ"),
                ("steam-launcher", "Steam"),
                ("openvpn", "VPN command line client"),
            )
        )
        upgradable = "Listing...\n" + "\n".join(
            f"{name}/stable 2.0 {arch} [upgradable from: 1.0]"
            for name, arch in (
                ("firefox", "amd64"),
                ("linux-image-amd64", "amd64"),
                ("libssl3:amd64", "amd64"),
                ("winehq-stable", "amd64"),
                ("steam-launcher", "amd64"),
                ("openvpn", "amd64"),
            )
        )
        packages = self.provider([completed(installed), completed(upgradable)]).list_all_packages()

        visible = {package.name for package in packages if package.update_available}
        self.assertEqual(
            visible,
            {
                "firefox", "linux-image-amd64", "libssl3:amd64",
                "winehq-stable", "steam-launcher", "openvpn",
            },
        )
        self.assertEqual(len(visible), 6)

    def test_zero_updates_is_a_successful_empty_inventory(self):
        provider = self.provider([completed("demo\t1\t10\tdemo\tinstalled"), completed("Listeleme...\n")])
        packages = provider.list_all_packages()
        self.assertEqual([package.name for package in packages if package.update_available], [])

    def test_timeout_is_not_reported_as_zero_updates(self):
        provider = self.provider([BackendError("Komut zaman aşımına uğradı")])
        with self.assertRaisesRegex(BackendError, "zaman"):
            provider._upgradable_packages_with_versions()

    def test_nonzero_exit_is_not_reported_as_zero_updates(self):
        provider = self.provider([completed(stderr="E: cache unavailable", returncode=100)])
        with self.assertRaisesRegex(BackendError, "kod 100"):
            provider._upgradable_packages_with_versions()

    def test_multiarch_rows_keep_both_architectures(self):
        parsed = _parse_apt_upgradable_output(
            "libdemo/stable 2 amd64 [upgradable from: 1]\n"
            "libdemo/stable 2 i386 [upgradable from: 1]\n"
        )
        self.assertEqual(parsed, {"libdemo:amd64": "2", "libdemo:i386": "2"})

    def test_translated_header_warnings_held_and_phased_annotations_do_not_hide_rows(self):
        parsed = _parse_apt_upgradable_output(
            "Auflistung...\n"
            "held-package/vendor 2 amd64 [upgradable from: 1] [held]\n"
            "phased-package/stable 3 amd64 [upgradable from: 2] [phased 20%]\n"
        )
        self.assertEqual(parsed, {"held-package": "2", "phased-package": "3"})

    def test_malformed_package_row_fails_the_inventory(self):
        with self.assertRaisesRegex(BackendError, "ayrıştırılamadı"):
            _parse_apt_upgradable_output("broken/stable\n")

    def test_cached_graphical_inventory_cannot_hide_fresh_system_updates(self):
        stale_apps = [
            UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        ]
        packages = [
            PackageInfo(name, "1", 10, "", True, "2")
            for name in ("linux-image-amd64", "libssl3:amd64", "openvpn")
        ]
        catalog = build_update_catalog(stale_apps, packages, SOURCE_APT)
        self.assertEqual(
            {item.application.package_name for item in catalog},
            {"linux-image-amd64", "libssl3:amd64", "openvpn"},
        )
        self.assertTrue(all(item.group == "system" for item in catalog))

    def test_multiarch_catalog_does_not_deduplicate_an_architecture(self):
        apps = [
            UnifiedApplication(
                "apt:libdemo:amd64", "Demo", SOURCE_APT,
                package_name="libdemo:amd64", update_available=True,
            )
        ]
        packages = [
            PackageInfo("libdemo:amd64", "1", 10, "", True, "2"),
            PackageInfo("libdemo:i386", "1", 10, "", True, "2"),
        ]
        catalog = build_update_catalog(apps, packages, SOURCE_APT)
        self.assertEqual(
            {item.application.package_name for item in catalog},
            {"libdemo:amd64", "libdemo:i386"},
        )


class TestExactAptStoreSearch149(unittest.TestCase):
    def registry(self, run):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry._command_exists = lambda command: command == "apt-cache"
        registry._run = run
        registry._metadata = {}
        return registry

    def test_exact_notepadqq_match_is_prominent_and_requires_candidate(self):
        def run(command, timeout=30):
            if command[1] == "search":
                return completed("notepadqq - Notepad++-like editor for Linux\nnotepadqq-data - data files\n")
            return completed("notepadqq:\n  Candidate: 2.0.0\nnotepadqq-data:\n  Candidate: 2.0.0\n")

        items = self.registry(run)._search_apt("notepadqq")
        self.assertEqual(items[0].app_id, "notepadqq")
        self.assertEqual(items[0].version, "2.0.0")

    def test_exact_match_falls_back_to_policy_when_text_search_misses_it(self):
        def run(command, timeout=30):
            if command[1] == "search":
                return completed()
            if command[1] == "policy":
                return completed("notepadqq:\n  Installed: (none)\n  Candidate: 2.0.0\n")
            return completed("Package: notepadqq\nDescription-en: Editor from configured APT repositories\n")

        items = self.registry(run)._search_apt("notepadqq")
        self.assertEqual([(item.app_id, item.version) for item in items], [("notepadqq", "2.0.0")])

    def test_unavailable_exact_package_is_a_genuine_zero_result(self):
        def run(command, timeout=30):
            if command[1] == "policy":
                return completed("notepadqq:\n  Installed: (none)\n  Candidate: (none)\n")
            return completed()

        self.assertEqual(self.registry(run)._search_apt("notepadqq"), [])

    def test_candidate_query_failure_is_provider_failure(self):
        def run(command, timeout=30):
            if command[1] == "search":
                return completed("notepadqq - editor\n")
            return completed(stderr="E: damaged cache", returncode=100)

        with self.assertRaisesRegex(BackendError, "damaged cache"):
            self.registry(run)._search_apt("notepadqq")

    def test_malformed_search_output_is_not_a_zero_result(self):
        registry = self.registry(lambda command, timeout=30: completed("not a package row\n"))
        with self.assertRaisesRegex(BackendError, "malformed"):
            registry._search_apt("editor")

    def test_regex_special_query_is_passed_as_one_argument_without_exact_lookup(self):
        commands = []

        def run(command, timeout=30):
            commands.append(command)
            return completed()

        self.assertEqual(self.registry(run)._search_apt("[notepad.*"), [])
        self.assertEqual(commands, [["apt-cache", "search", "--", "[notepad.*"]])

    def test_existing_eric_and_evolution_searches_remain_available(self):
        for query in ("eric", "evolution"):
            with self.subTest(query=query):
                def run(command, timeout=30, query=query):
                    if command[1] == "search":
                        return completed(f"{query} - graphical application\n")
                    return completed(f"{query}:\n  Candidate: 1.0\n")

                items = self.registry(run)._search_apt(query)
                self.assertEqual([item.app_id for item in items], [query])


class TestStoreProviderOutcomes149(unittest.TestCase):
    def registry(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry.PROVIDER_TIMEOUT_SECONDS = 1
        registry.native_manager = SOURCE_APT
        registry.provider_errors = []
        registry.missing_sources = []
        registry._search_cache = {}
        registry._partial_search_cache = {}
        registry._metadata = {}
        registry.last_search_metrics = {}
        registry.last_search_source_states = {}
        registry._search_context = threading.local()
        registry._command_exists = lambda _command: True
        registry._persist_search_cache = lambda: None
        return registry

    def test_only_flathub_results_are_preserved(self):
        registry = self.registry()
        flatpak = StoreResult(
            "Notepadqq", "com.notepadqq.Notepadqq", "Editor", SOURCE_FLATPAK, "2", "flathub"
        )
        registry._search_apt = lambda _query: []
        registry._search_flatpak = lambda _query: [flatpak]
        results = registry.search("notepadqq", sources={SOURCE_APT, SOURCE_FLATPAK})
        self.assertEqual([(item.source, item.app_id) for item in results], [(SOURCE_FLATPAK, flatpak.app_id)])

    def test_only_apt_results_are_preserved(self):
        registry = self.registry()
        apt = StoreResult("notepadqq", "notepadqq", "Editor", SOURCE_APT, "2", "apt")
        registry._search_apt = lambda _query: [apt]
        registry._search_flatpak = lambda _query: []
        results = registry.search("notepadqq", sources={SOURCE_APT, SOURCE_FLATPAK})
        self.assertEqual([(item.source, item.app_id) for item in results], [(SOURCE_APT, "notepadqq")])

    def test_partial_provider_failure_keeps_live_result_and_diagnostic(self):
        registry = self.registry()
        apt = StoreResult("notepadqq", "notepadqq", "Editor", SOURCE_APT, "2", "apt")
        registry._search_apt = lambda _query: [apt]

        def fail(_query):
            raise BackendError("Flathub unavailable")

        registry._search_flatpak = fail
        results = registry.search("notepadqq", sources={SOURCE_APT, SOURCE_FLATPAK})
        self.assertEqual([item.app_id for item in results], ["notepadqq"])
        self.assertTrue(any("Flathub unavailable" in error for error in registry.provider_errors))
        self.assertEqual(registry.last_search_source_states[SOURCE_FLATPAK], "unavailable")


if __name__ == "__main__":
    unittest.main()
