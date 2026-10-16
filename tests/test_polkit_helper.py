#!/usr/bin/env python3
"""Authorization proof-of-concept contracts.

The polkit helper and policy are review artifacts, not shipped code. These
tests pin the security properties the review depends on: a fixed operation
enum, strict target validation and a policy that never grants arbitrary
execution.
"""

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "packaging" / "polkit" / "sourcedock-helper"
POLICY_PATH = ROOT / "packaging" / "polkit" / "dev.aliafacan.sourcedock.policy"

OPERATION_PLACEHOLDER = "dev.aliafacan.sourcedock.manage-local-packages"
HELPER_INSTALL_PATH = "/usr/libexec/sourcedock/sourcedock-helper"


def _load_helper():
    loader = importlib.machinery.SourceFileLoader("sourcedock_polkit_helper", str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestPolkitHelper(unittest.TestCase):
    def setUp(self):
        self.helper = _load_helper()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.helper.STAGING_ROOT = str(self.root) + "/"

    def test_install_local_uses_fixed_apt_argv_without_shell(self):
        package = self.root / "example.deb"
        package.write_bytes(b"fixture")
        command = self.helper.build_command("install-local", str(package))
        self.assertEqual(command[0], self.helper.APT_GET)
        self.assertIn("--", command)
        self.assertEqual(command[-1], str(package))
        self.assertNotIn("sudo", command)
        self.assertNotIn("-c", command)

    def test_install_local_rejects_paths_outside_the_staging_root(self):
        outside = Path(tempfile.gettempdir()) / "sourcedock-escape.deb"
        with self.assertRaises(ValueError):
            self.helper.build_command("install-local", str(outside))

    def test_install_local_rejects_symlinks(self):
        real = self.root / "real.deb"
        real.write_bytes(b"fixture")
        link = self.root / "link.deb"
        link.symlink_to(real)
        with self.assertRaises(ValueError):
            self.helper.build_command("install-local", str(link))

    def test_remove_package_validates_the_package_id(self):
        command = self.helper.build_command("remove-package", "example-package")
        self.assertEqual(command[:3], [self.helper.APT_GET, "purge", "-y"])
        for bad in ("", "example package", "../evil", "Pkg;rm -rf /", "-o" + "x" * 250):
            with self.subTest(target=bad), self.assertRaises(ValueError):
                self.helper.build_command("remove-package", bad)

    def test_unknown_operation_is_refused(self):
        with self.assertRaises(ValueError):
            self.helper.build_command("run-anything", "example")

    def test_main_refuses_invalid_arguments_without_exec(self):
        self.assertEqual(self.helper.main([str(HELPER_PATH)]), 2)
        self.assertEqual(self.helper.main([str(HELPER_PATH), "run-anything", "x"]), 2)
        self.assertEqual(self.helper.main([str(HELPER_PATH), "remove-package", "../evil"]), 2)


class TestPolkitPolicy(unittest.TestCase):
    def setUp(self):
        self.tree = ElementTree.parse(POLICY_PATH)

    def test_action_is_scoped_to_the_fixed_helper(self):
        action = self.tree.find(f".//action[@id='{OPERATION_PLACEHOLDER}']")
        self.assertIsNotNone(action)
        annotations = {
            node.get("key"): (node.text or "").strip()
            for node in action.findall("annotate")
        }
        self.assertEqual(
            annotations.get("org.freedesktop.policykit.exec.path"), HELPER_INSTALL_PATH
        )

    def test_policy_never_allows_unauthenticated_any_session(self):
        for tag in ("allow_any", "allow_inactive"):
            node = self.tree.find(f".//defaults/{tag}")
            self.assertIsNotNone(node)
            self.assertEqual((node.text or "").strip(), "no")


if __name__ == "__main__":
    unittest.main()
