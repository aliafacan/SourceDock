"""Headless UI/cache contracts for the v1.4.9 reliability fixes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.models import ApplicationSnapshot, SOURCE_APT, UnifiedApplication
from sourcedock.ui.views.installed_view import InstalledViewMixin
from sourcedock.ui.views.updates_view import UpdatesViewMixin


class _ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        self.target()


class TestUpdateViewContracts149(unittest.TestCase):
    def view(self):
        view = UpdatesViewMixin()
        view.preferences = SimpleNamespace(language="en", notifications_enabled=False)
        view.application_registry = MagicMock()
        view.application_registry.native_provider.source = SOURCE_APT
        view.application_registry.load.return_value = ApplicationSnapshot([])
        view.application_registry.list_packages.return_value = []
        view.updates_loading = False
        view.applications_busy = False
        view.updates_refresh_btn = MagicMock()
        view.updates_state = MagicMock()
        view.updates_stat_labels = {}
        view.updates_reboot_banner = MagicMock()
        view._render_updates_model = MagicMock()
        view._render_updates_status = MagicMock()
        view._refresh_updates_texts = MagicMock()
        view._refresh_update_count = MagicMock()
        return view

    def test_refresh_invalidates_application_inventory_without_refreshing_apt_metadata(self):
        view = self.view()
        with (
            patch("sourcedock.ui.views.updates_view.threading.Thread", _ImmediateThread),
            patch("sourcedock.ui.views.updates_view.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)),
        ):
            view._reload_updates_async()
        view.application_registry.invalidate_application_cache.assert_called_once_with()
        view.application_registry.refresh_update_cache.assert_not_called()

    def test_failed_provider_query_never_renders_the_up_to_date_state(self):
        view = self.view()
        view._finish_updates_load([], ["apt: query failed"], None)
        self.assertEqual(view.updates_state.show_state.call_args.args[0], "Update check incomplete")


class TestDateDisplayContracts149(unittest.TestCase):
    def test_desktop_mtime_never_fabricates_install_or_update_dates(self):
        view = InstalledViewMixin()
        view.preferences = SimpleNamespace(language="en")
        with tempfile.TemporaryDirectory() as directory:
            desktop = Path(directory) / "demo.desktop"
            desktop.write_text("[Desktop Entry]\n", encoding="utf-8")
            os.utime(desktop, (1_900_000_000, 1_900_000_000))
            app = UnifiedApplication(
                "apt:demo", "Demo", SOURCE_APT, desktop_file=str(desktop), package_name="demo"
            )
            self.assertEqual(view._get_app_date_fallback(app), ("Unknown", "Unknown"))

    def test_known_install_date_survives_desktop_file_update(self):
        view = InstalledViewMixin()
        view.preferences = SimpleNamespace(language="en")
        app = UnifiedApplication(
            "apt:demo", "Demo", SOURCE_APT,
            installed_date="2026-01-01", last_updated="2026-02-01",
        )
        self.assertEqual(view._get_app_date_fallback(app), ("2026-01-01", "2026-02-01"))


class TestApplicationCacheContracts149(unittest.TestCase):
    def test_legacy_cache_with_inferred_dates_is_invalidated(self):
        registry = ApplicationRegistry.__new__(ApplicationRegistry)
        registry.PERSISTED_CACHE_TTL_SECONDS = 3600
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "installed-applications.json"
            cache.write_text(
                json.dumps({
                    "saved_at": 9_999_999_999,
                    "applications": [{"id": "apt:demo", "name": "Demo", "source": SOURCE_APT}],
                }),
                encoding="utf-8",
            )
            registry._persisted_application_cache_path = cache
            self.assertIsNone(registry._read_persisted_application_cache())

    def test_cache_from_previous_schema_or_app_version_is_invalidated(self):
        registry = ApplicationRegistry.__new__(ApplicationRegistry)
        registry.PERSISTED_CACHE_TTL_SECONDS = 3600
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "installed-applications.json"
            cache.write_text(
                json.dumps({
                    "version": 2,
                    "app_version": "1.4.8",
                    "saved_at": 9_999_999_999,
                    "applications": [{
                        "id": "apt:demo", "name": "Demo", "source": SOURCE_APT,
                    }],
                }),
                encoding="utf-8",
            )
            registry._persisted_application_cache_path = cache
            self.assertIsNone(registry._read_persisted_application_cache())


if __name__ == "__main__":
    unittest.main()
