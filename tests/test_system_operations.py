"""Stable system inventory and independent, safely serialized transactions."""

import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.flatpak import FlatpakProvider
from sourcedock.backend.snap import SnapProvider
from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.core.errors import BackendError
from sourcedock.core.runner import CommandRunner, OperationContext
from sourcedock.core.transactions import transaction_scope


class TestSystemInventory(unittest.TestCase):
    def test_flatpak_runtimes_exist_without_update_discovery(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = [
            subprocess.CompletedProcess([], 0, "org.example.Editor\tEditor\t1\tflathub\tsystem\t1 MB\n", ""),
            subprocess.CompletedProcess([], 0, "org.example.Platform\tPlatform\t1\tflathub\tsystem\t10 MB\tShared runtime\n", ""),
        ]
        scanner = MagicMock()
        scanner.list_entries.return_value = []
        provider = FlatpakProvider(runner, scanner)
        with patch.object(provider, "_update_ids") as updates:
            apps = provider.list_applications(include_updates=False)
        updates.assert_not_called()
        self.assertEqual([app.package_name for app in apps], ["org.example.Editor", "org.example.Platform"])
        self.assertEqual(apps[1].category, "System")
        self.assertFalse(apps[1].update_available)

    def test_snap_bases_exist_after_their_updates_are_installed(self):
        runner, scanner = MagicMock(), MagicMock()
        runner.command_exists.return_value = True
        scanner.list_entries.return_value = []
        provider = SnapProvider(runner, scanner)
        with (patch.object(provider, "_snap_metadata", return_value={"core22": "1", "gnome-46-2404": "2"}),
              patch.object(provider, "_update_names") as updates,
              patch.object(provider, "_get_snap_size_and_dates", return_value=(1, "", ""))):
            apps = provider.list_applications(include_updates=False)
        updates.assert_not_called()
        self.assertEqual({app.package_name for app in apps}, {"core22", "gnome-46-2404"})
        self.assertTrue(all(app.category == "System" and not app.update_available for app in apps))

    def test_failed_runtime_read_does_not_replace_inventory_with_only_gui_apps(self):
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = [subprocess.CompletedProcess([], 0, "", ""),
                                  subprocess.CompletedProcess([], 1, "", "runtime query failed")]
        with self.assertRaises(BackendError):
            FlatpakProvider(runner, MagicMock()).list_applications(include_updates=False)

    def test_scoped_refresh_never_queries_other_providers(self):
        registry = ApplicationRegistry.__new__(ApplicationRegistry)
        snap = MagicMock(source="snap")
        other = MagicMock(source="flatpak")
        registry.providers = [snap, other]
        snap.list_applications.return_value = []
        registry.load_sources({"snap"})
        snap.list_applications.assert_called_once_with(include_updates=False)
        other.list_applications.assert_not_called()


class TestConcurrentTransactions(unittest.TestCase):
    def test_different_package_managers_run_concurrently(self):
        runner = CommandRunner()
        runner.host_bridge_available = False
        first_started, release, second_started = (threading.Event() for _ in range(3))

        def execute(wrapped, command, *args, **kwargs):
            if command[0] == "snap":
                first_started.set()
                release.wait(3)
            else:
                second_started.set()
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(runner, "_run_subprocess", side_effect=execute):
            first = threading.Thread(target=lambda: runner.run(["snap", "refresh", "editor"]))
            second = threading.Thread(target=lambda: runner.run(["flatpak", "update", "org.example.Editor"]))
            first.start()
            try:
                self.assertTrue(first_started.wait(1))
                second.start()
                self.assertTrue(second_started.wait(1), "Flatpak was blocked by Snap")
            finally:
                release.set()
                first.join(3)
                if second.ident:
                    second.join(3)

    def test_same_package_database_waits_and_reports_queue(self):
        entered, release, queued, second_entered = (threading.Event() for _ in range(4))

        def first():
            with transaction_scope(["apt-get", "install", "editor"]):
                entered.set()
                release.wait(3)

        def second():
            with transaction_scope(["dpkg", "-i", "editor.deb"], on_wait=queued.set):
                second_entered.set()

        a, b = threading.Thread(target=first), threading.Thread(target=second)
        a.start()
        try:
            self.assertTrue(entered.wait(1))
            b.start()
            self.assertTrue(queued.wait(1))
            self.assertFalse(second_entered.is_set())
        finally:
            release.set()
            a.join(3)
            if b.ident:
                b.join(3)
        self.assertTrue(second_entered.is_set())

    def test_lingering_snap_only_blocks_snap_mutations(self):
        context = OperationContext("fixture-lingering", ["snap", "refresh", "editor"], False)
        context.is_critical = context.lingering = True
        with patch.dict(CommandRunner._active_critical_registry, {context.op_id: context}, clear=True):
            self.assertTrue(CommandRunner.has_global_active_critical_operation())
            self.assertTrue(CommandRunner.has_global_active_critical_operation(resource="snap"))
            self.assertFalse(CommandRunner.has_global_active_critical_operation(resource="flatpak"))
            self.assertTrue(CommandRunner.has_global_active_critical_operation(resource="global"))

    def test_authorization_is_isolated_between_bound_operations(self):
        runner = CommandRunner()
        ready, release = threading.Event(), threading.Event()
        values = []

        def first():
            runner.bind_thread_op("one")
            runner.set_sudo_password("one-secret")
            ready.set()
            release.wait(3)
            values.append(runner._sudo_password)
            runner.clear_sudo_password()
            runner.unbind_thread_op("one")

        thread = threading.Thread(target=first)
        thread.start()
        try:
            self.assertTrue(ready.wait(1))
            runner.bind_thread_op("two")
            runner.set_sudo_password("two-secret")
            runner.clear_sudo_password()
            self.assertIsNone(runner._sudo_password)
            runner.unbind_thread_op("two")
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(values, ["one-secret"])
