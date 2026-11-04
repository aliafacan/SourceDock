"""Cross-source app identity and install-first migration without host mutations."""

from dataclasses import replace
import unittest
from unittest.mock import MagicMock

from sourcedock.core.errors import BackendError
from sourcedock.core.models import ApplicationSnapshot, StoreResult, UnifiedApplication
from sourcedock.core.app_identity import matching_installations, store_identity
from sourcedock.backend.source_switch import SourceSwitchPlan, verify_destination, remove_previous_after_install


def chrome(source="apt", package="google-chrome-stable", path="/usr/share/applications"):
    return UnifiedApplication(f"{source}:{package}", "Google Chrome", source,
                              package_name=package, desktop_file=f"{path}/{package}.desktop", install_path=path)


class TestSourceIdentity(unittest.TestCase):
    def test_chrome_apt_and_flatpak_match_without_name_guessing(self):
        result = StoreResult("Google Chrome", "com.google.Chrome", "", "flatpak", "1", "flathub")
        self.assertEqual(matching_installations(result, [chrome()]), [chrome()])
        self.assertEqual(store_identity(result), store_identity(replace(result, source="apt", app_id="google-chrome-stable")))

    def test_chromium_and_chrome_beta_are_not_chrome_stable(self):
        target = StoreResult("Google Chrome", "com.google.Chrome", "", "flatpak", "1", "flathub")
        self.assertEqual(matching_installations(target, [chrome(package="chromium"), chrome(package="google-chrome-beta")]), [])

    def test_equal_display_names_do_not_authorize_replacing_unrelated_packages(self):
        target = StoreResult("Google Chrome", "unrelated-app", "", "snap", "1", "stable")
        self.assertEqual(matching_installations(target, [chrome()]), [])

    def test_metadata_desktop_identity_matches_a_different_native_package_name(self):
        app = chrome(package="browser")
        app = replace(app, desktop_file="/usr/share/applications/org.example.Browser.desktop")
        target = StoreResult("Browser", "org.example.Browser", "", "flatpak", "1", "flathub")
        self.assertEqual(matching_installations(target, [app]), [app])

    def test_known_store_variants_link_metadata_to_an_installed_native_package(self):
        target = StoreResult("Editor", "org.example.Editor", "", "flatpak", "1", "flathub")
        native = replace(target, source="apt", app_id="editor-app", identity="org.example.Editor")
        app = chrome(package="editor-app")
        self.assertEqual(matching_installations(target, [app], [native]), [app])

    def test_runtime_entries_and_non_application_results_cannot_be_switched(self):
        target = StoreResult("Platform", "core22", "", "snap", "1", "stable")
        runtime = replace(chrome(source="snap", package="core22"), desktop_file="", category="System")
        self.assertEqual(matching_installations(target, [runtime]), [])
        self.assertEqual(matching_installations(replace(target, app_id="google-chrome-stable", is_application=False), [chrome()]), [])

    def test_multiple_launchers_are_deduplicated_but_flatpak_scopes_are_preserved(self):
        target = StoreResult("Google Chrome", "google-chrome-stable", "", "apt", "1", "apt")
        user = chrome("flatpak", "com.google.Chrome", "/home/test/.local/share/flatpak/app/com.google.Chrome")
        system = replace(user, install_path="/var/lib/flatpak/app/com.google.Chrome")
        self.assertEqual(len(matching_installations(target, [user, replace(user, id="other-launcher"), system])), 2)


class TestSourceSwitchSafety(unittest.TestCase):
    def setUp(self):
        self.old = chrome()
        self.new = chrome("flatpak", "com.google.Chrome", "/var/lib/flatpak/app/com.google.Chrome")
        self.target = StoreResult("Google Chrome", "com.google.Chrome", "", "flatpak", "2", "flathub")
        self.plan = SourceSwitchPlan(self.target, self.old)
        self.registry = MagicMock()
        self.registry.load_sources.side_effect = lambda sources: ApplicationSnapshot([self.new] if sources == {"flatpak"} else [self.old])

    def test_new_installation_is_verified_before_old_removal_without_purge(self):
        events = []
        def read(sources):
            events.append(next(iter(sources)))
            return ApplicationSnapshot([self.new] if sources == {"flatpak"} else [self.old])
        self.registry.load_sources.side_effect = read
        self.registry.runner._wait_for_critical_transactions.side_effect = lambda: events.append("wait")
        self.registry.remove.side_effect = lambda *a, **kw: events.append("remove")
        remove_previous_after_install(self.registry, self.plan)
        self.assertEqual(events, ["wait", "flatpak", "apt", "remove"])
        self.registry.remove.assert_called_once_with(self.old, purge=False)

    def test_missing_or_failed_destination_keeps_previous_installation(self):
        for snapshot in (ApplicationSnapshot([]), ApplicationSnapshot([self.new], provider_errors=["flatpak: failed"])):
            with self.subTest(snapshot=snapshot):
                self.registry.load_sources.side_effect = None
                self.registry.load_sources.return_value = snapshot
                with self.assertRaises(BackendError):
                    remove_previous_after_install(self.registry, self.plan)
                self.registry.remove.assert_not_called()

    def test_different_package_in_destination_does_not_count_as_success(self):
        self.registry.load_sources.side_effect = None
        self.registry.load_sources.return_value = ApplicationSnapshot([replace(self.new, package_name="org.chromium.Chromium")])
        with self.assertRaises(BackendError):
            verify_destination(self.registry, self.target)
        self.registry.remove.assert_not_called()

    def test_incomplete_previous_inventory_cannot_trigger_removal(self):
        self.registry.load_sources.side_effect = [ApplicationSnapshot([self.new]),
            ApplicationSnapshot([self.old], provider_errors=["apt: incomplete"])]
        with self.assertRaises(BackendError):
            remove_previous_after_install(self.registry, self.plan)
        self.registry.remove.assert_not_called()

    def test_cancelled_cleanup_stops_before_verification_or_removal(self):
        self.registry.runner._check_task_cancelled.side_effect = BackendError("cancelled")
        with self.assertRaises(BackendError):
            remove_previous_after_install(self.registry, self.plan)
        self.registry.load_sources.assert_not_called()
        self.registry.remove.assert_not_called()

    def test_cleanup_failure_keeps_new_installation(self):
        self.registry.remove.side_effect = BackendError("old package is busy")
        with self.assertRaises(BackendError):
            remove_previous_after_install(self.registry, self.plan)
        self.registry.remove.assert_called_once_with(self.old, purge=False)

    def test_unrelated_or_same_source_replacement_is_rejected(self):
        for old in (replace(self.old, package_name="chromium", desktop_file="chromium.desktop"), self.new):
            with self.subTest(old=old):
                with self.assertRaises(BackendError):
                    remove_previous_after_install(self.registry, SourceSwitchPlan(self.target, old))
                self.registry.remove.assert_not_called()

    def test_supported_source_pairs_work_in_both_directions(self):
        sources = ("apt", "dnf", "pacman", "zypper", "flatpak", "snap")
        for previous in sources:
            for destination in sources:
                if previous == destination:
                    continue
                with self.subTest(previous=previous, destination=destination):
                    old_id = "org.mozilla.firefox" if previous == "flatpak" else "firefox"
                    new_id = "org.mozilla.firefox" if destination == "flatpak" else "firefox"
                    old = replace(self.old, source=previous, package_name=old_id, desktop_file=old_id + ".desktop")
                    new = replace(self.new, source=destination, package_name=new_id, desktop_file=new_id + ".desktop")
                    target = replace(self.target, source=destination, app_id=new_id)
                    registry = MagicMock()
                    registry.load_sources.side_effect = [ApplicationSnapshot([new]), ApplicationSnapshot([old])]
                    remove_previous_after_install(registry, SourceSwitchPlan(target, old))
                    registry.remove.assert_called_once_with(old, purge=False)

    def test_previous_package_already_removed_is_a_safe_noop(self):
        self.registry.load_sources.side_effect = [ApplicationSnapshot([self.new]), ApplicationSnapshot([])]
        remove_previous_after_install(self.registry, self.plan)
        self.registry.remove.assert_not_called()
