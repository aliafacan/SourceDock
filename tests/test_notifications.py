#!/usr/bin/env python3
"""Tests for desktop notifications."""

from unittest.mock import MagicMock, patch
import unittest

from sourcedock.core.notifications import send_desktop_notification


class TestDesktopNotifications(unittest.TestCase):
    def test_empty_notification_returns_false(self):
        self.assertFalse(send_desktop_notification("", ""))

    def test_missing_runner_command_returns_false(self):
        runner = MagicMock()
        runner.command_exists.return_value = False
        result = send_desktop_notification("Title", "Body", runner=runner)
        self.assertFalse(result)
        runner.run.assert_not_called()

    def test_runner_executes_notify_send_with_arguments(self):
        import subprocess
        runner = MagicMock()
        runner.command_exists.return_value = True
        expected_cmd = ["notify-send", "-a", "SourceDock", "-i", "software-update-available", "-u", "normal", "Update", "3 packages available"]
        runner.run.return_value = subprocess.CompletedProcess(expected_cmd, 0, "", "")

        result = send_desktop_notification("Update", "3 packages available", icon="software-update-available", runner=runner)
        self.assertTrue(result)
        runner.run.assert_called_once_with(expected_cmd, timeout=5)

    def test_runner_returns_false_on_non_zero_exit(self):
        import subprocess
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.return_value = subprocess.CompletedProcess(["notify-send"], 1, "", "notification daemon error")

        result = send_desktop_notification("Title", "Body", runner=runner)
        self.assertFalse(result)

    def test_runner_handles_timeout_and_exceptions(self):
        import subprocess
        runner = MagicMock()
        runner.command_exists.return_value = True
        runner.run.side_effect = subprocess.TimeoutExpired(cmd=["notify-send"], timeout=5)

        result = send_desktop_notification("Title", "Body", runner=runner)
        self.assertFalse(result)

    def test_system_notify_send_called_via_subprocess(self):
        with patch("shutil.which", return_value="/usr/bin/notify-send"), \
             patch("subprocess.run") as sub_run:
            sub_run.return_value = MagicMock(returncode=0)
            result = send_desktop_notification("Title", "Body", runner=None)
            self.assertTrue(result)
            sub_run.assert_called_once_with(
                ["/usr/bin/notify-send", "-a", "SourceDock", "-i", "sourcedock", "-u", "normal", "Title", "Body"],
                check=False,
                timeout=5,
                capture_output=True,
            )

    def test_no_system_notify_send_returns_false(self):
        with patch("shutil.which", return_value=None):
            result = send_desktop_notification("Title", "Body", runner=None)
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()

