#!/usr/bin/env python3
"""Design-token and theme-CSS contracts.

These tests are the guard rails for the regression where an unsupported
``@media`` at-rule silently broke every styled window. They also record the
measured WCAG AA contrast audit so a palette edit cannot quietly lower it.
"""

import unittest

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.theme import PALETTES, get_theme_css


def _relative_luminance(color: str) -> float:
    value = color.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class TestThemeCssLoading(unittest.TestCase):
    def test_css_loads_for_every_palette_and_scale(self):
        for theme in ("dark", "light"):
            for scale in ("90", "100", "110", "125"):
                with self.subTest(theme=theme, scale=scale):
                    provider = Gtk.CssProvider()
                    provider.load_from_data(get_theme_css(theme, scale).encode("utf-8"))

    def test_css_never_contains_unsupported_media_rule(self):
        # GTK 3 CSS has no @media support; the motion preference must be applied
        # through the token layer instead of a media query.
        for theme in ("dark", "light"):
            self.assertNotIn("@media", get_theme_css(theme, "100"))

    def test_reduced_motion_disables_animations(self):
        normal = get_theme_css("dark", "100", reduced_motion=False)
        reduced = get_theme_css("dark", "100", reduced_motion=True)
        self.assertNotIn("transition-duration: 0s !important", normal)
        self.assertIn("transition-duration: 0s !important", reduced)
        self.assertIn("animation-duration: 0s !important", reduced)

    def test_custom_tokens_are_defined_for_every_palette(self):
        for theme, palette in PALETTES.items():
            css = get_theme_css(theme, "100", reduced_motion=False)
            for token, value in palette.items():
                with self.subTest(theme=theme, token=token):
                    self.assertIn(f"@define-color {token} {value};", css)


class TestContrastAudit(unittest.TestCase):
    """Documented WCAG AA audit for both palettes.

    Normal text targets 4.5:1. Status/border tokens are used as accent or
    large/bold text and must still reach at least 3:1.
    """

    NORMAL_TEXT_PAIRS = (
        ("text", "background"),
        ("text", "surface"),
        ("text", "surface_hover"),
        ("text", "sidebar"),
        ("text", "selection"),
        ("muted", "background"),
        ("muted", "surface"),
        ("muted", "surface_hover"),
        ("muted", "sidebar"),
        ("muted", "selection"),
        ("accent_text", "accent"),
    )
    ACCENT_PAIRS = (
        ("success", "surface"),
        ("success", "background"),
        ("warning", "surface"),
        ("warning", "background"),
        ("danger", "surface"),
        ("danger", "background"),
        ("focus", "surface"),
        ("focus", "background"),
    )

    def test_normal_text_meets_aa(self):
        for theme, palette in PALETTES.items():
            for foreground, background in self.NORMAL_TEXT_PAIRS:
                with self.subTest(theme=theme, pair=(foreground, background)):
                    ratio = contrast_ratio(palette[foreground], palette[background])
                    self.assertGreaterEqual(round(ratio, 2), 4.5, f"{theme} {foreground}/{background}")

    def test_status_accents_meet_large_text_aa(self):
        for theme, palette in PALETTES.items():
            for foreground, background in self.ACCENT_PAIRS:
                with self.subTest(theme=theme, pair=(foreground, background)):
                    ratio = contrast_ratio(palette[foreground], palette[background])
                    self.assertGreaterEqual(round(ratio, 2), 3.0, f"{theme} {foreground}/{background}")


if __name__ == "__main__":
    unittest.main()
