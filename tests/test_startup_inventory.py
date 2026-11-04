"""Restart discovery must reuse valid inventory and notice external mutations."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.models import ApplicationSnapshot, SOURCE_APT, UnifiedApplication


class TestStartupInventory(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.registry = registry = ApplicationRegistry.__new__(ApplicationRegistry)
        registry._persisted_application_cache_path = Path(directory.name) / "inventory.json"
        registry._application_cache_lock = threading.RLock()
        registry._application_cache = None
        registry._application_cache_at = 0
        registry.last_provider_metrics = {}
        registry._build_snapshot = lambda apps, errors, **kwargs: ApplicationSnapshot(list(apps), provider_errors=list(errors))
        self.app = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        self.provider = Mock(source=SOURCE_APT)
        self.provider.list_applications.return_value = [self.app]
        registry.providers = [self.provider]
        self.marker = "unchanged"
        fingerprint = patch("sourcedock.backend.manager.inventory_fingerprint", side_effect=lambda: self.marker)
        fingerprint.start()
        self.addCleanup(fingerprint.stop)

    def test_unchanged_restart_publishes_complete_inventory_without_provider_queries(self):
        self.registry.remember_inventory([self.app])
        publish = Mock()
        snapshot = self.registry.load_startup(publish)
        self.assertEqual(snapshot.applications, [self.app])
        publish.assert_called_once_with(snapshot, True)
        self.provider.list_applications.assert_not_called()

    def test_external_database_change_forces_fresh_read_without_update_queries(self):
        self.registry.remember_inventory([self.app])
        self.marker = "external-install"
        snapshot = self.registry.load_startup(Mock())
        self.provider.list_applications.assert_called_once_with(include_updates=False)
        self.assertEqual(snapshot.applications, [self.app])

    def test_unreadable_database_cannot_validate_cache(self):
        self.registry.remember_inventory([self.app])
        self.marker = None
        self.registry.load_startup(Mock())
        self.provider.list_applications.assert_called_once_with(include_updates=False)

    def test_expired_cache_forces_discovery(self):
        self.registry.remember_inventory([self.app])
        path = self.registry._persisted_application_cache_path
        raw = json.loads(path.read_text())
        raw["saved_at"] = 0
        path.write_text(json.dumps(raw))
        self.registry.load_startup(Mock())
        self.provider.list_applications.assert_called_once()

    def test_reconciled_removal_survives_restart(self):
        other = UnifiedApplication("apt:other", "Other", SOURCE_APT, package_name="other")
        self.registry.remember_inventory([self.app, other])
        self.registry.invalidate_application_cache()
        self.registry.remember_inventory([other])
        self.assertEqual(self.registry.load_startup(Mock()).applications, [other])
        self.provider.list_applications.assert_not_called()

    def test_database_change_during_scan_does_not_mark_old_results_current(self):
        def changed(**kwargs):
            self.marker = "changed-during-scan"
            return [self.app]
        self.provider.list_applications.side_effect = changed
        self.registry.load_progressive(Mock(), include_updates=False)
        self.registry.load_startup(Mock())
        self.assertEqual(self.provider.list_applications.call_count, 2)
