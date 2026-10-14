#!/usr/bin/env python3
"""Yardım sistemi, araç ipuçları ve sütun genişlikleri testleri."""

import unittest

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.i18n import TRANSLATIONS, t
from sourcedock.ui.views.help_view import HelpDialog, HelpViewMixin


class TestHelpAndTooltips(unittest.TestCase):
    """Yardım diyaloğu, yerelleştirilmiş araç ipuçları ve sütun testleri."""

    def test_i18n_keys_parity(self):
        """TR ve EN arasındaki yardım ve araç ipucu anahtarlarının tam olduğunu doğrular."""
        required_keys = [
            "help",
            "help_title",
            "help_subtitle",
            "help_tab_overview",
            "help_tab_features",
            "help_tab_installer",
            "help_tab_shortcuts",
            "help_overview_what_title",
            "help_overview_what_desc",
            "help_overview_formats_title",
            "help_overview_fmt_native",
            "help_overview_fmt_flatpak",
            "help_overview_fmt_snap",
            "help_overview_fmt_appimage",
            "help_overview_fmt_portable",
            "help_overview_fmt_local",
            "help_features_installed_title",
            "help_features_store_title",
            "help_features_packages_title",
            "help_features_operations_title",
            "help_installer_mini_title",
            "help_installer_smart_title",
            "help_installer_flow_title",
            "help_shortcuts_title",
            "help_shortcuts_f1",
            "help_shortcuts_ctrl_f",
            "help_shortcuts_f5",
            "help_shortcuts_delete",
            "help_shortcuts_escape",
            "help_tips_title",
            "help_tips_dnd",
            "help_tips_default",
            "help_tips_appimage",
            "tooltip_help",
            "tooltip_settings",
            "tooltip_installed_search",
            "tooltip_installed_refresh",
            "tooltip_installed_check_updates",
            "tooltip_installed_update_all",
            "tooltip_installed_launch",
            "tooltip_installed_update",
            "tooltip_installed_open_location",
            "tooltip_installed_remove",
            "tooltip_installed_bulk_remove",
            "tooltip_installed_permissions",
            "tooltip_installed_rollback",
            "tooltip_installed_changelog",
            "tooltip_installed_export",
            "tooltip_installed_export_selected",
            "tooltip_installed_install_file",
            "tooltip_installed_add_appimage",
            "tooltip_installed_flatpak_cleanup",
            "tooltip_installed_filter_all",
            "tooltip_installed_filter_updates",
            "tooltip_installed_filter_native",
            "tooltip_installed_filter_flatpak",
            "tooltip_installed_filter_snap",
            "tooltip_installed_filter_appimage",
            "tooltip_installed_filter_portable",
            "tooltip_installed_category",
            "tooltip_store_search_entry",
            "tooltip_store_search_btn",
            "tooltip_store_filter_all",
            "tooltip_store_filter_flatpak",
            "tooltip_store_filter_snap",
            "tooltip_store_filter_native",
            "tooltip_store_install",
            "tooltip_packages_search",
            "tooltip_packages_refresh",
            "tooltip_packages_filter_all",
            "tooltip_packages_filter_upgradable",
            "tooltip_packages_update_selected",
            "tooltip_packages_update_all",
            "tooltip_operations_refresh",
            "tooltip_operations_pause",
            "tooltip_operations_cancel",
            "tooltip_installer_install",
            "tooltip_installer_cancel",
            "tooltip_installer_launch",
            "tooltip_installer_retry",
            "tooltip_installer_close",
            "tooltip_installer_delete_after",
            "tooltip_installer_copy_apps",
            "tooltip_installer_create_shortcut",
            "tooltip_settings_language",
            "tooltip_settings_theme",
            "tooltip_settings_scale",
            "tooltip_settings_set_default",
        ]

        for lang in ("tr", "en"):
            for key in required_keys:
                self.assertIn(key, TRANSLATIONS[lang], f"Missing key '{key}' in '{lang}' translation.")
                val = t(lang, key)
                self.assertTrue(
                    len(val.strip()) > 0, f"Value for key '{key}' in '{lang}' should not be empty."
                )

    def test_packages_column_labels(self):
        """Paketler sekmesi sütun başlıklarının güncellendiğini doğrular."""
        self.assertEqual(t("tr", "packages_col_version"), "Kurulu Sürüm")
        self.assertEqual(t("tr", "packages_col_new_version"), "Yeni Sürüm")
        self.assertEqual(t("en", "packages_col_version"), "Installed Version")
        self.assertEqual(t("en", "packages_col_new_version"), "New Version")

    def test_help_dialog_instantiation(self):
        """Display mevcut olduğunda HelpDialog nesnesinin hatasız oluştuğunu doğrular."""
        if not Gtk.init_check()[0]:
            self.skipTest("GUI display (X11/Wayland) mevcut değil.")

        dialog = HelpDialog(language="tr")
        self.assertIsNotNone(dialog.stack)
        pages = dialog.stack.get_children()
        self.assertEqual(len(pages), 4, "HelpDialog 4 adet stack sayfası içermelidir.")
        dialog.destroy()


if __name__ == "__main__":
    unittest.main()
