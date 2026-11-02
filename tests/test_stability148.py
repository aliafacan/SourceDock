"""v1.4.8 regressions. All package commands use fakes; GTK runs on Xvfb."""
import subprocess
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.apt_transactions import AptTransaction, PackageState, changes, snapshot
from sourcedock.core.errors import AuthRequiredError, BackendError
from sourcedock.core.runner import CommandRunner, OperationState
from sourcedock.ui.components.view_state import ApplicationViewState


def result(code=0, text="", error=""):
    return subprocess.CompletedProcess([], code, text, error)


class TestAuthentication148(unittest.TestCase):
    def setUp(self):
        self.runner = CommandRunner()
        self.runner.set_sudo_password("not-for-logs")

    def test_package_errors_never_trigger_auth_retry(self):
        for text in ("password database permission denied", "incorrect dependency", "sudo: 1 incorrect password attempt"):
            with self.subTest(text=text), self.assertRaises(BackendError) as caught:
                self.runner._raise_for_privileged_result(result(100, text), ["apt-get", "remove", "demo"])
            self.assertNotIsInstance(caught.exception, AuthRequiredError)

    def test_successful_remove_authenticates_once_and_never_replays(self):
        with patch.object(self.runner, "_wait_for_apt_locks"), patch.object(self.runner, "_execute_privileged_command", return_value=result()) as execute, patch.object(self.runner, "run", side_effect=[result(1), result()]) as run:
            self.runner.run_privileged(["apt-get", "remove", "demo"])
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(run.call_args_list[1].args[0], ["sudo", "-S", "-p", "", "-v"])
        self.assertNotIn("not-for-logs", str(run.call_args_list[1].args))
        self.assertIsNone(self.runner._sudo_password)

    def test_wrong_password_does_not_execute_package_command(self):
        with patch.object(self.runner, "_wait_for_apt_locks"), patch.object(self.runner, "_execute_privileged_command") as execute, patch.object(self.runner, "run", side_effect=[result(1), result(1, error="sudo: 1 incorrect password attempt")]):
            with self.assertRaises(AuthRequiredError) as caught:
                self.runner.run_privileged(["apt-get", "remove", "demo"])
        self.assertTrue(caught.exception.password_failed)
        execute.assert_not_called()
        self.assertIsNone(self.runner._sudo_password)

    def test_auth_expiry_after_mutation_cannot_replay_whole_task(self):
        self.runner.bind_thread_op("batch")
        self.runner._tasks["batch"].mutation_started = True
        with patch.object(self.runner, "_run_privileged_locked", side_effect=AuthRequiredError("expired")):
            with self.assertRaises(BackendError) as caught:
                self.runner.run_privileged(["fake"])
        self.assertNotIsInstance(caught.exception, AuthRequiredError)
        self.runner.unbind_thread_op()

    def test_redacts_before_clearing_failed_credentials(self):
        with self.assertRaises(BackendError) as caught:
            self.runner._raise_for_privileged_result(result(1, "not-for-logs is not in sudoers"), ["sudo", "-v"], auth_only=True)
        self.assertNotIn("not-for-logs", str(caught.exception))
        self.assertIsNone(self.runner._sudo_password)

    def test_root_without_sudo_uses_direct_argv_without_password(self):
        with patch("sourcedock.core.runner.shutil.which", return_value=None), \
             patch("sourcedock.core.runner.os.geteuid", return_value=0), \
             patch.object(self.runner, "_wait_for_apt_locks"), \
             patch.object(self.runner, "_execute_privileged_command", return_value=result()) as execute:
            self.runner.run_privileged(["apt-get", "remove", "demo"])
        execute.assert_called_once_with(
            ["apt-get", "remove", "demo"], 900, None, False, direct_root=True
        )

    def test_password_is_sent_to_the_real_sudo_command_via_stdin(self):
        with patch.object(self.runner, "run", return_value=result()) as run:
            self.runner._execute_privileged_command(["true"], 30, None, False)
        self.assertEqual(run.call_args.args[0], ["sudo", "-k", "-S", "-p", "", "true"])
        self.assertEqual(run.call_args.kwargs["input_text"], "not-for-logs\n")
        self.assertNotIn("not-for-logs", str(run.call_args.args[0]))


class TestOperationCapabilities148(unittest.TestCase):
    def setUp(self):
        self.runner = CommandRunner()

    def tearDown(self):
        for ctx in list(self.runner._operations.values()):
            self.runner._finish_operation(ctx)

    def test_queued_cancel_prevents_first_command(self):
        self.runner.prepare_operation("queued")
        self.assertEqual(self.runner.request_cancel("queued"), "cancelled")
        self.runner.bind_thread_op("queued")
        with patch("subprocess.Popen") as spawn, self.assertRaises(BackendError):
            self.runner.run(["fake"])
        spawn.assert_not_called()
        self.runner.complete_task("queued", False)
        self.assertEqual(self.runner.operation_status("queued")["state"], "CANCELLED")

    def test_critical_request_is_pending_never_kills(self):
        self.runner.bind_thread_op("critical")
        ctx = self.runner._create_operation(["apt-get", "install", "demo"], allow_cancel=False)
        with patch("sourcedock.core.runner.terminate_process") as terminate:
            self.assertEqual(self.runner.request_cancel("critical"), "pending")
            self.assertFalse(self.runner.cancel_current("critical"))
        terminate.assert_not_called()
        self.assertFalse(ctx.cancelled)
        self.assertTrue(self.runner.operation_status("critical")["cancel_requested"])
        self.runner._finish_operation(ctx)
        self.runner.complete_task("critical", True)
        self.assertEqual(self.runner.operation_status("critical")["state"], "COMPLETED")

    def test_explicit_allow_cancel_cannot_override_critical_command(self):
        ctx = self.runner._create_operation(["apt-get", "install", "demo"], allow_cancel=True)
        with patch("sourcedock.core.runner.terminate_process") as terminate:
            self.assertFalse(self.runner.cancel_current(ctx.op_id))
        terminate.assert_not_called()

    def test_completed_operation_is_idempotent_and_not_cancelled(self):
        self.runner.prepare_operation("done")
        self.runner.complete_task("done", True)
        self.assertEqual(self.runner.request_cancel("done"), "finished")
        self.runner.complete_task("done", False)
        self.assertEqual(self.runner.operation_status("done")["state"], "COMPLETED")

    def test_targeted_request_does_not_touch_other_queued_task(self):
        self.runner.prepare_operation("one")
        self.runner.prepare_operation("two")
        self.runner.request_cancel("two")
        self.assertTrue(self.runner.operation_status("one")["can_cancel"])
        self.assertFalse(self.runner.operation_status("two")["can_cancel"])

    def test_generated_command_ids_are_unique_across_runners(self):
        other = CommandRunner()
        first = self.runner._create_operation(["query"], True)
        second = other._create_operation(["query"], True)
        self.assertNotEqual(first.op_id, second.op_id)
        other._finish_operation(second)


class TestAptEvidence148(unittest.TestCase):
    def setUp(self):
        self.runner = MagicMock()
        self.runner.has_global_active_critical_operation.return_value = False
        self.runner._apt_lock_holders.return_value = []
        self.base = PackageState("1.0", "amd64", False, True, "required", "installed")
        self.demo = PackageState("1.0", "amd64", True, False, "optional", "installed")
        self.before = {"base:amd64": self.base}
        self.after = {**self.before, "demo:amd64": self.demo}
        self.record = AptTransaction("test-evidence", ["apt-get", "install", "demo"], self.before, self.after)

    def test_snapshot_preserves_architecture_auto_and_essential(self):
        self.runner.run_read_only.side_effect = [result(text="base:amd64\t1.0\tamd64\tyes\trequired\tinstalled\ndemo:amd64\t1.0\tamd64\tno\toptional\tinstalled\n"), result(text="demo\n")]
        self.assertEqual(snapshot(self.runner), self.after)

    def test_half_configured_database_refused(self):
        self.runner.run_read_only.side_effect = [result(text="demo:amd64\t1.0\tamd64\tno\toptional\thalf-configured\n"), result()]
        with self.assertRaises(BackendError):
            snapshot(self.runner)

    def test_new_package_preview_is_read_only(self):
        self.runner.run_read_only.return_value = result(text="Remv demo [1.0]")
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.after):
            self.assertIn("demo:amd64", self.record.preview(self.runner))
        self.runner.run_privileged.assert_not_called()
        command = self.runner.run_read_only.call_args.args[0]
        self.assertIn("--simulate", command)
        self.assertEqual(command[-1], "demo:amd64-")
        self.assertFalse(hasattr(self.record, "execute"))

    def test_previous_version_unavailable_refused(self):
        self.record.before = {**self.before, "demo:amd64": self.demo}
        self.record.after = self.before
        self.runner.run_read_only.return_value = result(100)
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.before), self.assertRaisesRegex(BackendError, "unavailable"):
            self.record.preview(self.runner)

    def test_previous_version_available_is_previewed_without_downgrade(self):
        self.record.before = self.after
        self.record.after = self.before
        self.runner.run_read_only.side_effect = [result(text="Version: 1.0\n"), result(text="Inst demo (1.0)")]
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.before):
            self.assertIn("Inst demo", self.record.preview(self.runner))
        self.runner.run_privileged.assert_not_called()

    def test_stale_state_and_concurrent_operation_are_refused(self):
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.before), self.assertRaisesRegex(BackendError, "stale"):
            self.record.preview(self.runner)
        self.runner.has_global_active_critical_operation.return_value = True
        with self.assertRaisesRegex(BackendError, "running"):
            self.record.preview(self.runner)

    def test_protected_package_and_failed_simulation_are_refused(self):
        self.record.before = {"demo:amd64": self.demo}
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.after), self.assertRaisesRegex(BackendError, "protected"):
            self.record.preview(self.runner)
        self.record.before = self.before
        self.runner.run_read_only.side_effect = BackendError("broken dependencies")
        with patch("sourcedock.backend.apt_transactions.snapshot", return_value=self.after), self.assertRaisesRegex(BackendError, "dependencies"):
            self.record.preview(self.runner)

    def test_capture_and_finish_persist_actual_delta(self):
        self.runner.run_read_only.return_value = result(text="Inst demo (1.0)")
        with patch("sourcedock.backend.apt_transactions.snapshot", side_effect=[self.before, self.after]):
            record = AptTransaction.begin(self.runner, ["apt-get", "install", "demo"], "capture-test")
            record.finish(self.runner, result(text="installed"))
        self.assertEqual(list(changes(record.before, record.after)), ["demo:amd64"])
        self.assertEqual(record.returncode, 0)
        self.runner.run_privileged.assert_not_called()

    def test_missing_final_state_refuses_preview(self):
        self.record.after = None
        with self.assertRaises(BackendError):
            self.record.preview(self.runner)


class TestViewAnchor148(unittest.TestCase):
    def test_removed_anchor_uses_next_then_previous(self):
        state = ApplicationViewState(ordered_ids=["a", "m", "n", "z"], anchor_id="m")
        self.assertEqual(state.surviving_anchor({"a", "n", "z"}), "n")
        self.assertEqual(state.surviving_anchor({"a"}), "a")
        self.assertIsNone(state.surviving_anchor(set()))


class TestGtkStability148(unittest.TestCase):
    def setUp(self):
        from tests.test_ui_workflows import TestUiWorkflows
        TestUiWorkflows.setUp(self)
        from gi.repository import Gtk
        self.Gtk = Gtk

    def drain(self, seconds=0.12):
        from gi.repository import GLib
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def test_local_and_header_typing_sync_enter_and_button(self):
        self.window.pages.set_current_page(1)
        self.window.show_all()
        self.assertTrue(self.window.store_search_entry.get_visible())
        self.assertTrue(self.window.store_search_btn.get_visible())
        self.window.store_search_entry.set_text("notepadqq")
        self.assertEqual(self.window.header_search.get_text(), "notepadqq")
        with patch("sourcedock.ui.views.store_view.threading.Thread") as worker:
            self.window.store_search_entry.emit("activate")
            self.window.store_search_btn.clicked()
            self.assertEqual(worker.call_count, 1)
            self.assertTrue(self.window.store_search_entry.get_sensitive())
            self.window.header_search.set_text("eric")
            self.assertEqual(self.window.store_search_entry.get_text(), "eric")
            self.window.header_search.emit("activate")
            self.assertEqual(worker.call_count, 2)

    def test_clear_query_invalidates_delayed_results_and_reenables_button(self):
        self.window.pages.set_current_page(1)
        self.window.store_search_entry.set_text("old")
        with patch("sourcedock.ui.views.store_view.threading.Thread"):
            self.window.on_store_search()
        generation = self.window._store_search_generation
        self.window.header_search.set_text("")
        self.window._finish_store_search([], "stale error", generation)
        self.assertFalse(self.window.store_busy)
        self.assertTrue(self.window.store_search_btn.get_sensitive())
        self.assertNotEqual(self.window.store_search_status.get_text(), "stale error")

    def test_category_then_manual_query_clears_category_without_recursion(self):
        with patch("sourcedock.ui.views.store_view.threading.Thread"):
            self.window.pages.set_current_page(1)
            self.window.store_category_buttons[0][0].clicked()
            self.window.store_search_entry.set_text("custom")
        self.assertFalse(any(button.get_active() for button, _ in self.window.store_category_buttons))
        self.assertEqual(self.window.header_search.get_text(), "custom")

    def inventory(self, cards=False):
        from sourcedock.core.models import UnifiedApplication
        self.window.applications = [UnifiedApplication(id=f"apt:{i:03}", name=f"App {i:03}", source="apt", package_name=f"app{i}", category="Utility") for i in range(160)]
        self.window.applications_loading = False
        self.window.application_updates_loading = False
        self.window.application_filter_category = "__all__"
        self.window.application_filter_source = "all"
        self.window.application_search_text = ""
        self.window.show_all()
        self.window.pages.set_current_page(0)
        self.window.applications_view_stack.set_visible_child_name("cards" if cards else "table")
        self.window._render_applications_list()
        self.drain()

    def test_table_refresh_preserves_anchor_sort_multiple_selection_and_filters(self):
        self.inventory()
        store = self.window.applications_store
        store.set_sort_column_id(1, self.Gtk.SortType.DESCENDING)
        self.drain()
        adjustment = self.window.apps_scroller.get_vadjustment()
        adjustment.set_value((adjustment.get_upper() - adjustment.get_page_size()) / 2)
        self.drain()
        path = self.window.applications_tree.get_visible_range()[0]
        anchor = store[path][9].id
        selection = self.window.applications_tree.get_selection()
        selection.select_path(path)
        next_path = path.copy(); next_path.next()
        successor = store[next_path][9].id
        selection.select_path(next_path)
        self.window.applications = [app for app in self.window.applications if app.id != anchor]
        self.window._update_category_combo()
        self.window._render_applications_list()
        self.drain()
        self.assertEqual(store.get_sort_column_id(), (1, self.Gtk.SortType.DESCENDING))
        current = self.window.applications_tree.get_visible_range()[0]
        self.assertEqual(store[current][9].id, successor)
        self.assertGreater(adjustment.get_value(), 100)
        model, paths = selection.get_selected_rows()
        self.assertEqual({model[p][9].id for p in paths}, {successor})

    def test_cards_refresh_preserves_middle_anchor(self):
        self.inventory(cards=True)
        adjustment = self.window.cards_scroll.get_vadjustment()
        adjustment.set_value((adjustment.get_upper() - adjustment.get_page_size()) / 2)
        self.drain()
        children = self.window.applications_cards.get_children()
        anchor = next(child for child in children if child.get_allocation().y + child.get_allocation().height > adjustment.get_value())
        old = adjustment.get_value()
        self.window.applications = [a for a in self.window.applications if a.id != anchor.application_id]
        self.window._render_applications_list()
        self.drain()
        self.assertGreater(adjustment.get_value(), 100)
        self.assertLess(abs(adjustment.get_value() - old), 400)

    def test_partial_refresh_keeps_inventory_visible_and_stale_load_ignored(self):
        from sourcedock.core.models import ApplicationSnapshot
        self.inventory()
        self.window._application_load_generation = 2
        self.window._finish_applications_load(ApplicationSnapshot([]), False, 2)
        self.assertEqual(len(self.window.applications_store), 160)
        self.window._finish_applications_load(ApplicationSnapshot([]), True, 1)
        self.assertEqual(len(self.window.applications_store), 160)

    def progress(self):
        from sourcedock.ui.components.progress import OperationProgressWindow
        dialog = OperationProgressWindow("Test", "Demo", self.window, language="en")
        self.addCleanup(dialog.destroy)
        return dialog

    def test_apt_download_percentage_resets_for_unpack_and_configure_in_both_languages(self):
        for unpack, configure in [("Unpacking eric (1.0)", "Setting up eric (1.0)"), ("eric paketi açılıyor", "eric yapılandırılıyor")]:
            dialog = self.progress()
            dialog.append_log("1% [1 eric 1024 B/100 MB 1%]")
            self.assertAlmostEqual(dialog._progress.get_fraction(), .01)
            dialog.append_log(unpack)
            self.assertFalse(dialog._progress.get_show_text())
            self.assertIsNotNone(dialog._pulse_source)
            dialog.append_log(configure)
            self.assertEqual(dialog._title_label.get_text(), "Configuring packages")

    def test_get_lines_and_incidental_percent_do_not_invent_download_progress(self):
        dialog = self.progress()
        for line in ("Need to get 100 MB of archives.", "100 MB arşiv indirilecek.", "Get:1 https://example.test stable/main eric all 1.0 [100 MB]", "password file 1% damaged"):
            dialog.append_log(line)
            self.assertFalse(dialog._progress.get_show_text())
            self.assertIsNotNone(dialog._pulse_source)

    def test_silent_operation_expires_percentage_and_finish_is_idempotent(self):
        dialog = self.progress()
        dialog.append_log("30% [1 eric 3 MB/10 MB]")
        dialog._last_measurement = time.monotonic() - 10
        dialog._expire_measurement()
        self.assertFalse(dialog._progress.get_show_text())
        self.assertFalse(dialog._done)
        dialog.finish(True, "done")
        dialog.append_log("1% [late output]")
        dialog.finish(False, "late error")
        self.assertEqual(dialog._progress.get_fraction(), 1.0)
        self.assertEqual(dialog._title_label.get_text(), "Completed")

    def test_failed_operation_has_no_success_percentage(self):
        dialog = self.progress()
        dialog.finish(False, "dependency failed")
        self.assertFalse(dialog._progress.get_show_text())
        self.assertEqual(dialog._progress.get_fraction(), 0)

    def test_operations_lambda_uses_explicit_identity_and_keeps_selection(self):
        runner = CommandRunner()
        self.window._register_active_op("demo", "apt install demo", "demo", None, cancel_fn=lambda: None, runner=runner, op_id="real")
        self.window.operations_tree.get_selection().select_path(0)
        self.assertTrue(self.window.operations_cancel_btn.get_sensitive())
        self.window._update_op_row("demo", .1, "Downloading")
        self.window._poll_operation_rows()
        self.assertIsNotNone(self.window.operations_tree.get_selection().get_selected()[1])
        self.window._on_operations_cancel()
        self.assertTrue(runner.operation_status("real")["cancel_requested"])
        self.window._unregister_active_op("demo", False, "cancelled")

    def test_late_auth_callback_does_not_restart_completed_task(self):
        self.window.applications_busy = False
        with patch.object(self.window, "_ask_sudo_password") as ask:
            self.window._handle_application_auth_required(AuthRequiredError("late"), "remove", lambda: None, "applications_removed", "applications_progress_remove", True, "demo", False)
        ask.assert_not_called()
