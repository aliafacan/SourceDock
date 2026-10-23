import time
import unittest
from threading import Event
import sys
import subprocess
from pathlib import Path
import tempfile

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.errors import BackendError
from sourcedock.core.models import ApplicationSnapshot, SOURCE_APT, SOURCE_SNAP, StoreResult, UnifiedApplication
from sourcedock.core.runner import CommandRunner
from sourcedock.store.registry import StoreRegistry


class _FakeInstalledProvider:
    def __init__(self, source, result, delay=0.0):
        self.source = source
        self.result = result
        self.delay = delay

    def list_applications(self):
        if self.delay:
            time.sleep(self.delay)
        return self.result


class TestProviderTimeouts(unittest.TestCase):
    def test_read_only_timeout_terminates_process_group(self):
        runner = CommandRunner()
        started = time.perf_counter()
        with self.assertRaises(BackendError):
            runner.run_read_only(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=0.04,
            )
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertIsNone(runner._current_process)

    def test_progressive_application_load_returns_fast_provider_before_stalled_provider(self):
        fast = UnifiedApplication("apt:editor", "Editor", SOURCE_APT, package_name="editor")
        registry = ApplicationRegistry.__new__(ApplicationRegistry)
        registry.providers = [
            _FakeInstalledProvider(SOURCE_APT, [fast]),
            _FakeInstalledProvider(SOURCE_SNAP, [], delay=0.25),
        ]
        registry.last_provider_metrics = {}
        registry._build_snapshot = lambda apps, errors, include_hidden=True: ApplicationSnapshot(
            list(apps), provider_errors=list(errors)
        )
        snapshots = []

        started = time.perf_counter()
        snapshot = registry.load_progressive(
            lambda current, complete: snapshots.append((current, complete)),
            provider_timeout_seconds=0.04,
        )
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.15)
        self.assertEqual([app.name for app in snapshot.applications], ["Editor"])
        self.assertTrue(snapshots[-1][1])
        self.assertIn("snap: timeout", snapshot.provider_errors[0])
        self.assertEqual(registry.last_provider_metrics["timed_out"], [SOURCE_SNAP])

    def test_store_search_keeps_partial_results_and_does_not_cache_timeout(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry.PROVIDER_TIMEOUT_SECONDS = 0.04
        registry.native_manager = SOURCE_APT
        registry.provider_errors = []
        registry.missing_sources = []
        registry._search_cache = {}
        registry._partial_search_cache = {}
        registry._metadata = {}
        registry.last_search_metrics = {}
        fast = StoreResult("Editor", "editor", "A useful editor", SOURCE_APT, "1", "apt")
        registry._command_exists = lambda _command: True
        registry._search_apt = lambda _query: [fast]

        slow_started = Event()

        def slow_snap(_query):
            slow_started.set()
            time.sleep(0.25)
            return []

        snap_calls = []
        published_states = []

        def counted_slow_snap(query):
            snap_calls.append(query)
            return slow_snap(query)

        registry._search_snap = counted_slow_snap
        callbacks = []
        started = time.perf_counter()
        results = registry.search(
            "editor",
            sources={SOURCE_APT, SOURCE_SNAP},
            on_partial=lambda current, complete: (
                callbacks.append((current, complete)),
                published_states.append(dict(registry.last_search_source_states)),
            ),
            provider_timeout_seconds=0.04,
        )
        elapsed = time.perf_counter() - started

        self.assertTrue(slow_started.is_set())
        self.assertLess(elapsed, 0.15)
        self.assertEqual([result.app_id for result in results], ["editor"])
        self.assertTrue(callbacks[-1][1])
        self.assertTrue(registry.last_search_metrics["timed_out"])
        self.assertNotIn(("editor", (SOURCE_APT, SOURCE_SNAP)), registry._search_cache)
        self.assertTrue(any("SNAP: timeout" in error for error in registry.provider_errors))
        self.assertTrue(any(states.get(SOURCE_APT) == "live" for states in published_states))

        hot_results = registry.search("editor", sources={SOURCE_APT, SOURCE_SNAP})
        self.assertEqual([result.app_id for result in hot_results], ["editor"])
        self.assertEqual(snap_calls, ["editor"])
        self.assertTrue(registry.last_search_metrics["partial_cache"])

    def test_cached_results_expose_non_live_source_state(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry.native_manager = SOURCE_APT
        registry.provider_errors = []
        registry.missing_sources = []
        registry._search_cache = {}
        registry._partial_search_cache = {}
        registry._metadata = {}
        registry.last_search_metrics = {}
        registry._command_exists = lambda _command: True
        result = StoreResult("Editor", "editor", "", SOURCE_APT, "1", "apt")
        registry._search_apt = lambda _query: [result]
        registry._search_snap = lambda _query: []

        registry.search("editor", sources={SOURCE_APT, SOURCE_SNAP})
        self.assertEqual(registry.last_search_source_states[SOURCE_APT], "live")
        registry.search("editor", sources={SOURCE_APT, SOURCE_SNAP})
        self.assertEqual(registry.last_search_source_states[SOURCE_APT], "cached")

    def test_repeated_snap_timeouts_leave_no_search_workers(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry.PROVIDER_TIMEOUT_SECONDS = 0.04
        registry.native_manager = SOURCE_APT
        registry.provider_errors = []
        registry.missing_sources = []
        registry._search_cache = {}
        registry._partial_search_cache = {}
        registry._metadata = {}
        registry.last_search_metrics = {}
        registry._command_exists = lambda _command: True

        def slow_snap(_query):
            registry._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=30)
            return []

        registry._search_snap = slow_snap
        for index in range(20):
            with self.assertRaises(BackendError):
                registry.search(
                    f"timeout-{index}",
                    sources={SOURCE_SNAP},
                    provider_timeout_seconds=0.04,
                )
        time.sleep(0.15)
        import threading

        self.assertFalse(
            any(thread.name.startswith("sourcedock-store-search") for thread in threading.enumerate())
        )

    def test_snap_retry_after_timeout_returns_live_result_without_cached_error(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry.PROVIDER_TIMEOUT_SECONDS = 0.03
        registry.native_manager = SOURCE_APT
        registry.provider_errors = []
        registry.missing_sources = []
        registry._search_cache = {}
        registry._partial_search_cache = {}
        registry._metadata = {}
        registry.last_search_metrics = {}
        registry._command_exists = lambda _command: True
        calls = []

        def retrying_snap(query):
            calls.append(query)
            if len(calls) == 1:
                time.sleep(0.12)
                return []
            return [StoreResult("Firefox", "firefox", "", SOURCE_SNAP, "1", "stable")]

        registry._search_snap = retrying_snap
        with self.assertRaises(BackendError):
            registry.search("firefox", sources={SOURCE_SNAP}, provider_timeout_seconds=0.03)
        time.sleep(0.15)
        results = registry.search("firefox", sources={SOURCE_SNAP}, provider_timeout_seconds=0.03)

        self.assertEqual([item.app_id for item in results], ["firefox"])
        self.assertEqual(calls, ["firefox", "firefox"])
        self.assertEqual(registry.last_search_source_states[SOURCE_SNAP], "live")
        self.assertFalse(registry.last_search_metrics.get("partial_cache", False))

    def test_store_partial_cache_survives_restart_without_becoming_full_cache(self):
        result = StoreResult("Editor", "editor", "A useful editor", SOURCE_APT, "1", "apt")
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "sourcedock" / "store-search.json"
            key = ("editor", (SOURCE_APT, SOURCE_SNAP))

            writer = StoreRegistry.__new__(StoreRegistry)
            writer._search_cache = {}
            writer._search_cache_saved_at = {}
            writer._search_cache_complete = {}
            writer._partial_search_cache = {
                key: (
                    time.monotonic() + 30,
                    [result],
                    [],
                    {},
                    {SOURCE_APT: "live", SOURCE_SNAP: "unavailable"},
                )
            }
            writer._search_cache_path = str(cache_path)
            writer._persist_search_cache()

            restored = StoreRegistry.__new__(StoreRegistry)
            restored._search_cache = {}
            restored._search_cache_saved_at = {}
            restored._search_cache_complete = {}
            restored._partial_search_cache = {}
            restored._search_cache_path = str(cache_path)
            restored._load_persistent_search_cache()
            restored.provider_errors = []
            restored.missing_sources = []
            restored.last_search_metrics = {}
            restored.last_search_source_states = {}
            restored._metadata = {}

            results = restored.search("editor", sources={SOURCE_APT, SOURCE_SNAP})
            self.assertEqual([item.name for item in results], ["Editor"])
            self.assertNotIn(key, restored._search_cache)
            self.assertEqual(restored.last_search_source_states[SOURCE_SNAP], "unavailable")

    def test_store_corrupt_disk_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "sourcedock" / "store-search.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{not-json", encoding="utf-8")
            registry = StoreRegistry.__new__(StoreRegistry)
            registry._search_cache = {}
            registry._search_cache_saved_at = {}
            registry._search_cache_complete = {}
            registry._partial_search_cache = {}
            registry._search_cache_path = str(cache_path)
            registry._load_persistent_search_cache()
            self.assertFalse(registry._search_cache)
            self.assertFalse(registry._partial_search_cache)

    def test_exact_apt_transitional_application_remains_visible(self):
        registry = StoreRegistry.__new__(StoreRegistry)
        registry._command_exists = lambda _command: True
        registry._run = lambda command, timeout=30: subprocess.CompletedProcess(
            command,
            0,
            "firefox - Transitional package - firefox -> firefox snap\n"
            "firefox-locale-tr - Firefox language pack\n",
            "",
        )
        registry._apt_candidate_versions = lambda _names: {"firefox": "2:134.0.1~tux2-snap"}
        registry._metadata = {}

        items = registry._search_apt("firefox")
        enriched = registry._enrich_results(items, "firefox")
        exact = next(item for item in enriched if item.app_id == "firefox")
        locale = next(item for item in enriched if item.app_id == "firefox-locale-tr")

        self.assertTrue(exact.is_application)
        self.assertFalse(locale.is_application)
