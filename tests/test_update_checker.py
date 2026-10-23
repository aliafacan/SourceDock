"""Tests for the optional GitHub release notification check."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from sourcedock.backend.update_checker import check_latest_release


class _Response:
    def __init__(self, payload: object):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class TestUpdateChecker(unittest.TestCase):
    def test_returns_newer_stable_release(self):
        opener = Mock(return_value=_Response({
            "tag_name": "v1.5.0",
            "name": "SourceDock 1.5.0",
            "html_url": "https://github.com/aliafacan/SourceDock/releases/tag/v1.5.0",
            "draft": False,
            "prerelease": False,
        }))

        release = check_latest_release("1.4.1", opener=opener)

        self.assertIsNotNone(release)
        self.assertEqual(release.version, "1.5.0")
        self.assertEqual(release.name, "SourceDock 1.5.0")
        opener.assert_called_once()
        self.assertEqual(opener.call_args.kwargs["timeout"], 6)

    def test_ignores_same_or_older_release(self):
        for tag in ("v1.4.1", "v1.4.0"):
            with self.subTest(tag=tag):
                release = check_latest_release(
                    "1.4.1",
                    opener=Mock(return_value=_Response({"tag_name": tag})),
                )
                self.assertIsNone(release)

    def test_ignores_draft_prerelease_and_invalid_payloads(self):
        payloads = (
            {"tag_name": "v1.5.0", "draft": True},
            {"tag_name": "v1.5.0", "prerelease": True},
            {"tag_name": "nightly"},
            {"name": "no tag"},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                release = check_latest_release(
                    "1.4.1", opener=Mock(return_value=_Response(payload))
                )
                self.assertIsNone(release)

    def test_network_failure_is_a_no_result(self):
        release = check_latest_release("1.4.1", opener=Mock(side_effect=OSError("offline")))
        self.assertIsNone(release)


if __name__ == "__main__":
    unittest.main()
