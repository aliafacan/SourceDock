"""Tests for the optional GitHub release notification check."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from sourcedock.backend.update_checker import ReleaseInfo, check_latest_release, download_release_package


class _Response:
    def __init__(self, payload: object):
        if isinstance(payload, bytes):
            self.payload = payload
        elif isinstance(payload, str):
            self.payload = payload.encode("utf-8")
        else:
            self.payload = json.dumps(payload).encode("utf-8")
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if _size is None or _size < 0:
            chunk = self.payload[self.offset :]
            self.offset = len(self.payload)
            return chunk
        chunk = self.payload[self.offset : self.offset + _size]
        self.offset += len(chunk)
        return chunk


class TestUpdateChecker(unittest.TestCase):
    def test_returns_newer_stable_release(self):
        opener = Mock(return_value=_Response({
            "tag_name": "v1.5.0",
            "name": "SourceDock 1.5.0",
            "html_url": "https://github.com/aliafacan/SourceDock/releases/tag/v1.5.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "sourcedock_1.5.0_all.deb",
                    "browser_download_url": "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb",
                },
                {
                    "name": "sourcedock_1.5.0_all.deb.sha256",
                    "browser_download_url": "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb.sha256",
                },
            ],
        }))

        release = check_latest_release("1.4.1", opener=opener)

        self.assertIsNotNone(release)
        self.assertEqual(release.version, "1.5.0")
        self.assertEqual(release.name, "SourceDock 1.5.0")
        self.assertIsNotNone(release.deb_url)
        self.assertIsNotNone(release.checksum_url)
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

    def test_download_release_package_verifies_checksum_before_replacing(self):
        package_data = b"fake deb payload"
        checksum = hashlib.sha256(package_data).hexdigest()
        release = ReleaseInfo(
            "1.5.0",
            "SourceDock 1.5.0",
            "https://github.com/aliafacan/SourceDock/releases/tag/v1.5.0",
            "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb",
            "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb.sha256",
        )
        opener = Mock(side_effect=[_Response(package_data), _Response(f"{checksum}  package.deb\n")])

        with tempfile.TemporaryDirectory() as directory:
            path = download_release_package(release, destination_dir=directory, opener=opener)
            self.assertEqual(Path(path).read_bytes(), package_data)
            self.assertTrue(Path(path).name.endswith("_all.deb"))

    def test_download_release_package_rejects_bad_checksum(self):
        release = ReleaseInfo(
            "1.5.0",
            "SourceDock 1.5.0",
            "https://github.com/aliafacan/SourceDock/releases/tag/v1.5.0",
            "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb",
            "https://github.com/aliafacan/SourceDock/releases/download/v1.5.0/sourcedock_1.5.0_all.deb.sha256",
        )
        opener = Mock(side_effect=[_Response(b"fake deb payload"), _Response("0" * 64)])

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "checksum"):
                download_release_package(release, destination_dir=directory, opener=opener)


if __name__ == "__main__":
    unittest.main()
