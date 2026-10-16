"""Cleanup plans never broaden targets or execute stale/unapproved plans."""

import unittest
from unittest.mock import MagicMock, patch

from sourcedock.backend.flatpak_cleanup import CleanupRef, apply_cleanup
from sourcedock.core.errors import BackendError


class TestFlatpakCleanup(unittest.TestCase):
    def test_scopes_and_exact_refs_are_preserved(self):
        runner = MagicMock()
        user = CleanupRef("user", "runtime/org.example.Runtime/x86_64/1.0")
        system = CleanupRef("system", "runtime/org.example.Other/aarch64/stable")
        with patch("sourcedock.backend.flatpak_cleanup.plan_cleanup", return_value=(user, system)):
            apply_cleanup(runner, (user, system))
        user_command = runner.run.call_args.args[0]
        system_command = runner.run_privileged.call_args.args[0]
        self.assertIn("--user", user_command)
        self.assertIn(user.ref, user_command)
        self.assertNotIn(system.ref, user_command)
        self.assertIn("--system", system_command)
        self.assertIn(system.ref, system_command)
        for command in (user_command, system_command):
            self.assertIn("--no-related", command)
            self.assertNotIn("--unused", command)
            self.assertNotIn("--delete-data", command)

    def test_changed_plan_does_not_remove_anything(self):
        runner = MagicMock()
        target = CleanupRef("user", "runtime/org.example.Runtime/x86_64/stable")
        with patch("sourcedock.backend.flatpak_cleanup.plan_cleanup", return_value=()):
            with self.assertRaises(BackendError):
                apply_cleanup(runner, (target,))
        runner.run.assert_not_called()
        runner.run_privileged.assert_not_called()

    def test_invalid_scope_or_ref_is_rejected_before_commands(self):
        runner = MagicMock()
        for target in (
            CleanupRef("all", "runtime/org.example.Runtime/x86_64/stable"),
            CleanupRef("user", "--all"),
            CleanupRef("system", "runtime/../../home/example"),
        ):
            with self.subTest(target=target), self.assertRaises(BackendError):
                apply_cleanup(runner, (target,))
        runner.run.assert_not_called()
        runner.run_privileged.assert_not_called()

    def test_empty_plan_is_a_noop(self):
        runner = MagicMock()
        apply_cleanup(runner, ())
        runner.run.assert_not_called()
        runner.run_privileged.assert_not_called()
