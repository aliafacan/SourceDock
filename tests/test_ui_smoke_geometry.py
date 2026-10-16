"""Focused checks for physical outer-frame evidence in the acceptance harness."""

from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.ui_smoke import (
    AppPreferences,
    Gtk,
    MainWindow,
    capture,
    fit_main_window_to_viewport,
    geometry_failures,
    intersect_rect,
    is_x11_display,
    measure_window_geometry,
    rect_inside,
    settle,
)


class RectangleGeometryTests(unittest.TestCase):
    def test_containment_checks_position_and_positive_area(self):
        self.assertTrue(rect_inside([10, 20, 100, 80], [10, 20, 100, 80]))
        self.assertFalse(rect_inside([9, 20, 100, 80], [10, 20, 100, 80]))
        self.assertFalse(rect_inside([10, 21, 100, 80], [10, 20, 100, 80]))
        self.assertFalse(rect_inside([10, 20, 0, 80], [10, 20, 100, 80]))

    def test_capture_intersection_does_not_invent_offscreen_pixels(self):
        self.assertEqual(intersect_rect([-5, -5, 1034, 778], [0, 0, 1024, 768]), [0, 0, 1024, 768])
        self.assertEqual(intersect_rect([1024, 0, 20, 20], [0, 0, 1024, 768]), [1024, 0, 0, 20])


class X11GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check()[0] or not is_x11_display():
            raise unittest.SkipTest("Requires isolated X11 with a window manager")
        try:
            wm = subprocess.run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK"],
                                capture_output=True, text=True, check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f"Window manager cannot be verified: {error}") from error
        if "window id # 0x" not in wm.stdout:
            raise unittest.SkipTest("No EWMH window manager on this display")

    def test_main_outer_fit_and_root_png_at_both_scales(self):
        for scale in ("100", "125"):
            with (
                self.subTest(scale=scale),
                patch.object(MainWindow, "reload_applications_async"),
                patch.object(MainWindow, "reload_packages_async"),
                patch.object(MainWindow, "_reload_updates_async"),
                patch("sourcedock.ui.window.Gtk.main_quit"),
            ):
                preferences = type("Preferences", (), {"load": lambda self: AppPreferences("en", "light", scale)})()
                window = MainWindow(preferences)
                try:
                    window.show_all()
                    settle()
                    natural = measure_window_geometry(window, (0, 0))
                    width, height = natural["root_screen"]
                    fitted = fit_main_window_to_viewport(window, width, height, root_fit=True)
                    self.assertEqual(fitted["status"], "PASS", fitted)
                    geometry = measure_window_geometry(window, (width, height))
                    self.assertEqual(geometry_failures(geometry), [], geometry)
                    with tempfile.TemporaryDirectory() as directory:
                        evidence = capture(window, Path(directory) / "frame.png", root_proof=True)
                        self.assertTrue(evidence["complete_outer_frame"], evidence)
                        for key, expected in (("file", geometry["outer_frame"][2:]),
                                              ("root_file", [width, height])):
                            header = (Path(directory) / evidence[key]).read_bytes()[:24]
                            self.assertEqual(list(struct.unpack(">II", header[16:24])), expected)
                finally:
                    window.destroy()

    def test_offscreen_dialog_is_failed_and_capture_is_marked_incomplete(self):
        dialog = Gtk.Dialog(title="Geometry acceptance test")
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.get_content_area().add(Gtk.Label(label="Outer-frame evidence"))
        dialog.set_default_size(320, 200)
        try:
            dialog.show_all()
            settle()
            initial = measure_window_geometry(dialog, (320, 200))
            root_width, root_height = initial["root_screen"]
            dialog.move(root_width - 40, root_height - 40)
            settle()
            geometry = measure_window_geometry(dialog, (320, 200))
            self.assertIn("outer_outside_workarea", geometry_failures(geometry))
            self.assertTrue(geometry["overflow_flags"]["essential_action_outside_workarea"])
            with tempfile.TemporaryDirectory() as directory:
                evidence = capture(dialog, Path(directory) / "offscreen.png", root_proof=True)
                self.assertFalse(evidence["complete_outer_frame"], evidence)
                self.assertNotEqual(evidence["pixel_size"], geometry["outer_frame"][2:])
        finally:
            dialog.destroy()


if __name__ == "__main__":
    unittest.main()
