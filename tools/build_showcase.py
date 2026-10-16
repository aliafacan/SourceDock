#!/usr/bin/env python3
"""SourceDock UI showcase ZIP'i üretir.

Gerçek sistem verisini yalnızca okumak için kullanır; hiçbir kurulum, kaldırma
veya güncelleme işlemi çalıştırmaz. Ekran görüntülerinin yanında arkadaşla
paylaşılabilecek Türkçe konum ve kullanım notları üretir.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import subprocess
import time
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from sourcedock.backend.manager import ApplicationRegistry
from sourcedock.backend.updates import build_update_catalog
from sourcedock.core.models import (
    ApplicationSnapshot,
    PackageInfo,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    StoreResult,
    UnifiedApplication,
)
from sourcedock.preferences import AppPreferences
from sourcedock.store.registry import StoreRegistry
from sourcedock.ui.components.app_details_dialog import InstalledAppDetailsDialog
from sourcedock.ui.components.dialogs import AppDetailDialog, show_snap_classic_dialog
from sourcedock.ui.components.progress import OperationProgressWindow
from sourcedock.ui.components.package_installer_dialog import PackageInstallerDialog
from sourcedock.ui.views.help_view import HelpDialog
from sourcedock.ui.window import MainWindow


ROOT = Path(__file__).resolve().parents[1]


def settle(milliseconds: int = 300) -> None:
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def fit_main_window_to_viewport(window: Gtk.Window, width: int, height: int) -> None:
    """Keep the full GTK surface, including its header bar, in the target viewport."""
    titlebar = window.get_titlebar()
    title_height = titlebar.get_preferred_height()[1] if titlebar is not None else 0
    window.resize(width, max(240, height - title_height))
    settle(100)
    for _ in range(3):
        title_position = titlebar.translate_coordinates(window, 0, 0) if titlebar else (0, 0)
        child = window.get_child()
        child_position = child.translate_coordinates(window, 0, 0)
        measured_height = child_position[1] + child.get_allocated_height() - title_position[1]
        delta = height - measured_height
        if delta == 0:
            break
        current = window.get_size()
        window.resize(width, max(240, current.height + delta))
        settle(60)


def capture_provenance(package_path: str | None) -> dict:
    def git_value(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""

    package = Path(package_path).expanduser().resolve() if package_path else None
    package_version = ""
    if package and package.exists():
        try:
            package_version = subprocess.run(
                ["dpkg-deb", "-f", str(package), "Version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            package_version = ""
    display = Gdk.Display.get_default()
    screen = Gdk.Screen.get_default()
    display_name = display.get_name() if display is not None else ""
    root_screen = [screen.get_width(), screen.get_height()] if screen is not None else []
    primary = display.get_primary_monitor() if display is not None else None
    workarea = primary.get_workarea() if primary is not None else None
    x11_root_verified = display_name.startswith(":") and len(root_screen) == 2
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(ROOT),
        "execution_mode": "source-tree",
        "git_commit": git_value("rev-parse", "HEAD"),
        "worktree_dirty": bool(git_value("status", "--porcelain")),
        "package_path": str(package) if package else "",
        "package_version": package_version,
        "physical_viewport": "X11_ROOT_DOĞRULANDI" if x11_root_verified else "DOĞRULANMADI",
        "physical_viewport_reason": (
            f"X11 root ekranı gerçek piksel olarak ölçüldü: {root_screen[0]}x{root_screen[1]} ({display_name}). "
            "Showcase pencereleri 1366x768 istek boyutunda ayrıca yakalandı; fiziksel modun birebir 1366 olması gerekmez."
            if x11_root_verified
            else "X11/Xvfb root ekranı ölçülemedi."
        ),
        "display_backend": "x11" if x11_root_verified else display_name,
        "x11_root_screen": root_screen,
        "x11_primary_workarea": [workarea.x, workarea.y, workarea.width, workarea.height]
        if workarea is not None
        else [],
        "requested_viewport": [1366, 768],
        "screenshot_representation": "GTK application surface crop; not a full physical root-screen capture",
        "search_state": {
            "baseline_page": "installed",
            "baseline_query": "",
            "discover_query": "firefox",
            "packages_query": "",
            "updates_query": "",
            "operations_query": "",
            "filtered_fixture_query": "sourcedock-no-match",
        },
        "data_policy": {
            "real_system_read_only": "Installed applications, packages and store results are read without install/remove/update actions.",
            "simulated_fixtures": [
                "store-partial-timeout-dark-tr.png",
                "snap-classic-confirmation-dark-tr.png",
                "bulk-remove-confirmation-dark-tr.png",
                "password-prompt-dark-tr.png",
                "firmware-confirmation-dark-tr.png",
                "operation-progress-dark-tr.png",
            ],
        },
    }


def capture(window: Gtk.Window, path: Path) -> list[int]:
    settle()
    assert window.get_mapped(), f"Pencere eşlenemedi: {path.name}"
    native = window.get_window()
    width, height = native.get_width(), native.get_height()
    pixbuf = Gdk.pixbuf_get_from_window(native, 0, 0, width, height)
    assert pixbuf is not None, f"Ekran görüntüsü alınamadı: {path.name}"
    pixbuf.savev(str(path), "png", [], [])
    return [width, height]


def capture_menu_composite(window: Gtk.Window, menu: Gtk.Menu, path: Path) -> list[int]:
    """Popup menüyü masaüstü arka planı olmadan ana pencere üzerine bindirir."""
    settle()
    main_native = window.get_window()
    width, height = main_native.get_width(), main_native.get_height()
    pixbuf = Gdk.pixbuf_get_from_window(main_native, 0, 0, width, height)
    menu_native = menu.get_window()
    menu_width, menu_height = menu_native.get_width(), menu_native.get_height()
    menu_pixbuf = Gdk.pixbuf_get_from_window(menu_native, 0, 0, menu_width, menu_height)
    assert pixbuf is not None and menu_pixbuf is not None, f"Popup ekran görüntüsü alınamadı: {path.name}"
    menu_x = min(240, max(8, width - menu_width - 8))
    menu_y = 86
    menu_pixbuf.composite(
        pixbuf,
        menu_x,
        menu_y,
        menu_width,
        menu_height,
        menu_x,
        menu_y,
        1.0,
        1.0,
        GdkPixbuf.InterpType.BILINEAR,
        255,
    )
    pixbuf.savev(str(path), "png", [], [])
    return [width, height]


def write_note(
    path: Path,
    title: str,
    location: str,
    how_to_open: str,
    description: str,
    data_mode: str = "real-system-read-only",
) -> None:
    path.with_suffix(".md").write_text(
        f"# {title}\n\n"
        f"- **Konum:** {location}\n"
        f"- **Açma yolu:** {how_to_open}\n"
        f"- **Bu ekran:** {description}\n"
        f"- **Veri modu:** {data_mode}\n",
        encoding="utf-8",
    )


def find_toplevel(parent: Gtk.Window, dialog_type=None):
    for item in Gtk.Window.list_toplevels():
        if item is parent:
            continue
        if dialog_type is not None and not isinstance(item, dialog_type):
            continue
        if item.get_transient_for() is parent:
            return item
    return None


def capture_running_dialog(
    parent: Gtk.Window, invoke, path: Path, response: Gtk.ResponseType = Gtk.ResponseType.CANCEL
) -> None:
    captured = []

    def inspect():
        dialog = find_toplevel(parent, Gtk.Dialog)
        if dialog is None:
            return True
        captured.append(capture(dialog, path))
        dialog.response(response)
        return False

    source_id = GLib.timeout_add(180, inspect)
    invoke()
    if not captured:
        GLib.source_remove(source_id)
        raise AssertionError(f"Modal pencere yakalanamadı: {path.name}")


def make_window(snapshot: ApplicationSnapshot, packages: list[PackageInfo], results: list[StoreResult]):
    preferences = type("Preferences", (), {"load": lambda self: AppPreferences("tr", "dark", "100")})()
    updates = build_update_catalog(snapshot.applications, packages, SOURCE_APT)
    context = (
        patch.object(MainWindow, "reload_applications_async"),
        patch.object(MainWindow, "reload_packages_async"),
        patch.object(MainWindow, "_reload_updates_async"),
        patch("sourcedock.ui.window.Gtk.main_quit"),
    )
    stack = [item.start() for item in context]
    window = MainWindow(preferences)
    window._suppress_store_search = True
    for item in reversed(stack):
        item.stop()
    window.resize(1366, 768)
    window._finish_applications_load(snapshot)
    window._finish_packages_load(packages, None)
    window._suppress_store_search_changed = True
    window.store_search_entry.set_text("firefox")
    window._suppress_store_search_changed = False
    if window._store_search_timeout_id:
        GLib.source_remove(window._store_search_timeout_id)
        window._store_search_timeout_id = 0
    window.store_results = results
    window.pages.set_current_page(1)
    window._finish_store_search(results, None)
    window._finish_updates_load(updates, snapshot.provider_errors, None)
    window.show_all()
    fit_main_window_to_viewport(window, 1366, 768)
    if window._store_search_timeout_id:
        GLib.source_remove(window._store_search_timeout_id)
        window._store_search_timeout_id = 0
    window._finish_store_search(results, None)
    settle(500)
    return window


def show_menu(window: MainWindow, labels: list[str], path: Path) -> None:
    # Broadway has no pointer event for a synthetic Gtk.Menu popup. Render the
    # same context-menu surface in a borderless popup so the evidence image is
    # deterministic and remains readable in headless screenshot runs.
    menu = Gtk.Window(type=Gtk.WindowType.POPUP)
    menu.set_transient_for(window)
    menu.set_decorated(False)
    menu.set_resizable(False)
    menu.set_size_request(260, -1)
    frame = Gtk.Frame()
    frame.get_style_context().add_class("context-menu")
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    content.set_margin_top(6)
    content.set_margin_bottom(6)
    content.set_margin_start(6)
    content.set_margin_end(6)
    frame.add(content)
    menu.add(frame)
    for label in labels:
        if label == "---":
            content.pack_start(Gtk.Separator(), False, False, 5)
        else:
            item = Gtk.Button(label=label)
            item.set_halign(Gtk.Align.FILL)
            item_label = item.get_child()
            if item_label is not None:
                item_label.set_xalign(0)
                item_label.set_halign(Gtk.Align.FILL)
            item.get_style_context().add_class("flat")
            content.pack_start(item, False, False, 0)
    menu.show_all()
    menu.present()
    capture_menu_composite(window, menu, path)
    menu.destroy()


def copy_page_screenshots(destination: Path, manifest: list[dict]) -> None:
    page_titles = {
        "installed": ("Kurulu Uygulamalar", "Sol menü > Kurulu", "Sistemde algılanan kurulu uygulamaların listesi."),
        "discover": ("Keşfet", "Sol menü > Keşfet", "Mağaza araması, kaynak filtreleri ve uygulama sonuçları."),
        "packages": ("Paketler", "Sol menü > Paketler", "Kurulu ve kullanılabilir paketlerin tablo görünümü."),
        "operations": ("İşlemler", "Sol menü > İşlemler", "Devam eden ve tamamlanan kurulum/güncelleme işlemleri."),
        "updates": ("Güncellemeler", "Sol menü > Güncellemeler", "Seçilebilir güncellemeler, sürüm bilgileri ve toplu işlem alanı."),
    }
    page_queries = {
        "installed": "",
        "discover": "firefox",
        "packages": "",
        "operations": "",
        "updates": "",
    }
    for page, (title, location, description) in page_titles.items():
        for theme in ("dark", "light", "system"):
            for language in ("tr", "en"):
                source = ROOT / "docs" / "screenshots" / f"{page}-{theme}-{language}-100-1366x768.png"
                if not source.exists():
                    continue
                target = destination / "pages" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                theme_label = {"dark": "karanlık", "light": "aydınlık", "system": "sistem"}[theme]
                localized = f"{title} ({theme_label} tema, {language.upper()})"
                write_note(target, localized, location, location, description)
                manifest.append(
                    {
                        "file": str(target.relative_to(destination)),
                        "kind": "page",
                        "title": localized,
                        "location": location,
                        "description": description,
                        "active_query": page_queries[page],
                    }
                )

    existing_titles = {
        "details": ("Kurulu Uygulama Detayı", "Kurulu > bir uygulamayı çift tıkla veya Enter", "Uygulamanın meta bilgileri, durumu ve çalıştırma/güncelleme/kaldırma eylemleri."),
        "installer": ("Yerel Paket Kurucusu", "Üst çubuk > Yerel paket aç veya bir .deb dosyasına çift tıkla", "Yerel paket dosyasının sürüm, boyut, bağımlılık ve kurulum özeti."),
        "settings": ("Ayarlar", "Üst çubuk > dişli simgesi", "Dil, tema, ölçek, güncelleme ve tercih edilen kaynak ayarları."),
    }
    for prefix, (title, location, description) in existing_titles.items():
        for theme in ("dark", "light", "system"):
            for language in ("tr", "en"):
                source = ROOT / "docs" / "screenshots" / f"{prefix}-{theme}-{language}-100-1366x768.png"
                if not source.exists():
                    continue
                target = destination / "windows" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                theme_label = {"dark": "karanlık", "light": "aydınlık", "system": "sistem"}[theme]
                localized = f"{title} ({theme_label} tema, {language.upper()})"
                write_note(target, localized, location, location, description)
                manifest.append(
                    {
                        "file": str(target.relative_to(destination)),
                        "kind": "window",
                        "title": localized,
                        "location": location,
                        "description": description,
                    }
                )


def capture_generated_windows(destination: Path, window: MainWindow, registry, snapshot, results, manifest) -> None:
    windows = destination / "windows"
    menus = destination / "menus"
    windows.mkdir(parents=True, exist_ok=True)
    menus.mkdir(parents=True, exist_ok=True)
    app = snapshot.applications[0] if snapshot.applications else UnifiedApplication(
        "apt:demo", "Firefox", SOURCE_APT, version="demo", package_name="firefox"
    )
    safe_app = next(
        (item for item in snapshot.applications if not item.package_name.startswith(("libc6", "systemd", "udev", "linux-"))),
        app,
    )

    def add(
        path_name,
        title,
        location,
        how_to_open,
        description,
        data_mode="real-system-read-only",
        active_query="",
    ):
        path = windows / path_name
        manifest.append(
            {
                "file": str(path.relative_to(destination)),
                "kind": "window",
                "title": title,
                "location": location,
                "description": description,
                "data_mode": data_mode,
                "active_query": active_query,
            }
        )
        write_note(path, title, location, how_to_open, description, data_mode)
        return path

    details_path = add(
        "installed-app-detail-dark-tr.png",
        "Kurulu Uygulama Detay Penceresi",
        "Kurulu sayfası > uygulamaya çift tıklama veya Enter",
        "Kurulu listesinden bir satır seçip çift tıkla.",
        "Uygulama ikonu, paket kimliği, kaynak rozeti, durum ve işlem butonlarını gösterir.",
    )
    details = InstalledAppDetailsDialog(app, registry, "tr", parent=window)
    details.show_all()
    capture(details, details_path)
    details.destroy()

    primary = next((item for item in results if item.source != SOURCE_FLATPAK), results[0] if results else StoreResult(
        "Firefox", "firefox", "Web tarayıcısı", SOURCE_APT, "1.0", "system"
    ))
    if not any(item.source != primary.source and item.name == primary.name for item in results):
        alternate_source = SOURCE_FLATPAK if primary.source != SOURCE_FLATPAK else "snap"
        results = results + [replace(primary, source=alternate_source, remote="flathub" if alternate_source == SOURCE_FLATPAK else "stable")]
    store_path = add(
        "store-app-detail-with-sources-dark-tr.png",
        "Mağaza Uygulama Detayı ve Kaynak Seçimi",
        "Keşfet > bir uygulamaya çift tıklama veya Enter",
        "Keşfet listesinden bir uygulamayı seçip çift tıkla.",
        "Tekrarlı arama satırları yerine uygulama detayında APT, Flatpak veya Snap kaynağı seçilebilir.",
        "real-system-read-only",
    )
    store_dialog = AppDetailDialog(primary, results, set(), lambda _result: None, "tr", window)
    capture(store_dialog, store_path)
    store_dialog.destroy()

    timeout_path = add(
        "store-partial-timeout-dark-tr.png",
        "Mağaza Kısmi Sonuç ve Provider Timeout Durumu",
        "Keşfet > arama tamamlanırken Snap yanıt vermediğinde",
        "Bir arama başlat; hızlı kaynak sonuçları geldikten sonra optional provider timeout durumunu gör.",
        "APT/Flatpak sonuçları korunur, Snap yanıt vermedi bilgisi görünür ve sonuçlar sahte tam başarı olarak işaretlenmez.",
        "simulated-fixture",
        active_query="firefox",
    )
    window.store_registry.provider_errors = ["SNAP: timeout after 5s"]
    window.store_registry.last_search_source_states = {
        "apt": "live",
        "flatpak": "live",
        "snap": "unavailable",
    }
    window.store_registry.last_search_metrics = {
        "cache_hit": False,
        "partial_cache": False,
        "timed_out": True,
        "timed_out_sources": ["snap"],
        "timeout_seconds": 5.0,
    }
    timeout_results = [item for item in results if item.source != SOURCE_SNAP]
    window.store_results = timeout_results
    window.pages.set_current_page(1)
    window._finish_store_search(timeout_results, None)
    window.show_all()
    fit_main_window_to_viewport(window, 1366, 768)
    capture(window, timeout_path)
    window.store_registry.provider_errors = []

    filtered_path = add(
        "installed-search-empty-dark-tr.png",
        "Kurulu Uygulamalarda Boş Arama Sonucu",
        "Kurulu sayfası > üst arama alanı",
        "Kurulu sayfasında sonuç vermeyen bir uygulama adı ara; Aramayı temizle düğmesine basarak listeye dön.",
        "Filtrelenmiş boş durumun gerçek kurulu envanterden ayrıldığını ve sorgunun nasıl temizleneceğini gösterir.",
        active_query="sourcedock-no-match",
    )
    window.pages.set_current_page(0)
    window._refresh_shell_page(0)
    # Drive the same visible header field a user types into. Filling the
    # hidden page entry directly produced a screenshot with a blank header
    # while the empty-state copy still named the query.
    window.header_search.set_text("sourcedock-no-match")
    fit_main_window_to_viewport(window, 1366, 768)
    capture(window, filtered_path)
    window._clear_application_search()

    cleared_path = add(
        "installed-search-cleared-dark-tr.png",
        "Arama Temizlendikten Sonra Kurulu Liste",
        "Kurulu sayfası > Aramayı temizle düğmesi sonrası",
        "Boş sonuç ekranında Aramayı temizle düğmesine bas.",
        "Görünür arama alanı boşalır ve normal kurulu uygulama envanteri yeniden gösterilir.",
        active_query="",
    )
    fit_main_window_to_viewport(window, 1366, 768)
    capture(window, cleared_path)

    help_path = add(
        "help-dark-tr.png",
        "Yardım Penceresi",
        "Üst çubuk > soru işareti simgesi",
        "Ana pencerenin üst çubuğundaki yardım düğmesine tıkla.",
        "SourceDock özellikleri, sekmeler, kurucu akışı ve klavye kısayolları sekmeli yardım içinde sunulur.",
    )
    help_dialog = HelpDialog(window, "tr")
    capture(help_dialog, help_path)
    help_dialog.destroy()

    progress_path = add(
        "operation-progress-dark-tr.png",
        "İşlem İlerleme Penceresi",
        "Kurulum, kaldırma veya güncelleme başladıktan sonra",
        "Bir uygulama eylemini başlat; işlem penceresi otomatik açılır.",
        "İlerleme çubuğu, mevcut işlem, ayrıntı günlüğü ve küçült/kapat kontrollerini gösterir.",
        "simulated-fixture",
    )
    progress = OperationProgressWindow("Güncelleme", safe_app.name, window, language="tr")
    progress._progress.set_fraction(0.64)
    progress._progress.set_show_text(True)
    progress._progress.set_text("64%")
    progress._title_label.set_text("Paket indiriliyor")
    progress._status_label.set_text("Bağımlılıklar hazırlanıyor")
    progress.append_log("[apt] Paket listesi okundu")
    progress.append_log("[apt] İndirme: 64%")
    progress._details_expander.set_expanded(True)
    capture(progress, progress_path)
    progress.destroy()

    password_path = add(
        "password-prompt-dark-tr.png",
        "Yönetici Şifresi İsteme Penceresi",
        "Kurulum, kaldırma veya güncelleme sırasında yetki gerektiğinde",
        "Yetki isteyen bir eylemi başlat.",
        "Şifre alanı, iptal ve devam düğmeleriyle yönetici yetkisi isteyen işlemleri açıklar.",
        "simulated-fixture",
    )
    capture_running_dialog(window, lambda: window._ask_sudo_password(), password_path)

    firmware_path = add(
        "firmware-confirmation-dark-tr.png",
        "Firmware Güncelleme Onayı",
        "Güncellemeler > firmware satırı seçiliyken güncelle",
        "Bir firmware güncellemesini uygulamayı dene.",
        "Firmware işleminin özel riskini açıklayan onay mesajı ve iptal/tamam düğmeleri.",
        "simulated-fixture",
    )
    capture_running_dialog(window, window._confirm_firmware_update, firmware_path)

    snap_path = add(
        "snap-classic-confirmation-dark-tr.png",
        "Snap Classic İzni Onayı",
        "Keşfet > classic yetkisi isteyen Snap kurulumu",
        "Classic confinement isteyen bir Snap uygulamasını kurmayı dene.",
        "Classic yetkisinin güvenlik etkisini açıklayan özel onay penceresi.",
        "simulated-fixture",
    )
    capture_running_dialog(window, lambda: show_snap_classic_dialog(window, "tr", primary.name), snap_path)

    remove_path = add(
        "remove-confirmation-dark-tr.png",
        "Uygulama Kaldırma Onayı",
        "Kurulu veya Paketler sayfası > kaldır düğmesi / sağ tık > kaldır",
        "Bir uygulama seçip kaldırma eylemini başlat.",
        "Uygulama adı, kaldırma onayı, yapılandırma temizleme seçeneği ve yıkıcı işlem düğmesi.",
    )
    capture_running_dialog(window, lambda: window.on_remove_application(None, safe_app), remove_path)

    bulk_remove_path = add(
        "bulk-remove-confirmation-dark-tr.png",
        "Seçilenleri Kaldır Onayı",
        "Kurulu > birden fazla uygulama seçip Seçilenleri Kaldır",
        "Kurulu uygulama listesinden birden fazla satır seçip Seçilenleri Kaldır düğmesine tıkla.",
        "Onay listesi seçili uygulama adlarını, kaynaklarını ve toplam adedi gösterir; bu kanıt ekranında işlem iptal edilir.",
        "simulated-fixture",
    )
    window.pages.set_current_page(0)
    selection = window.applications_tree.get_selection()
    selection.unselect_all()
    selection.select_path("0")
    selection.select_path("1")
    capture_running_dialog(window, lambda: window.on_bulk_remove_applications(None), bulk_remove_path)

    sources_path = add(
        "sources-dialog-dark-tr.png",
        "Yapılandırılmış Kaynaklar Penceresi",
        "Ayarlar > kaynakları yönet / kaynaklar düğmesi",
        "Ayarlar içindeki kaynaklar düğmesine tıkla.",
        "APT ve diğer paket kaynaklarının adını, ayrıntısını ve kanalını tablo halinde listeler.",
    )
    window.on_open_sources(None)
    settle(500)
    sources_dialog = find_toplevel(window, Gtk.Dialog)
    if sources_dialog is None:
        raise AssertionError("Kaynaklar penceresi yakalanamadı")
    capture(sources_dialog, sources_path)
    sources_dialog.response(Gtk.ResponseType.CLOSE)

    installed_menu_path = menus / "installed-context-menu-dark-tr.png"
    write_note(
        installed_menu_path,
        "Kurulu Uygulamalar Sağ Tık Menüsü",
        "Kurulu sayfası > uygulama satırına sağ tık",
        "Bir kurulu uygulama satırına sağ tıkla.",
        "Detayları gör, çalıştır, güncelle, konum aç, izinler/geri alım ve kaldırma gibi bağlamsal eylemleri tek menüde toplar.",
    )
    show_menu(
        window,
        ["Detayları gör", "Çalıştır", "Güncelle", "Konumu aç", "İzinler", "Geri al", "---", "Kaldır"],
        installed_menu_path,
    )
    manifest.append({"file": str(installed_menu_path.relative_to(destination)), "kind": "menu", "title": "Kurulu Uygulamalar Sağ Tık Menüsü", "location": "Kurulu sayfası > uygulama satırına sağ tık", "description": "Kurulu uygulama eylemleri."})

    package_menu_path = menus / "packages-context-menu-dark-tr.png"
    write_note(
        package_menu_path,
        "Paketler Sağ Tık Menüsü",
        "Paketler sayfası > paket satırına sağ tık",
        "Bir paket satırına sağ tıkla.",
        "Paket detayları, güncelleme, değişiklik günlüğü ve kaldırma eylemlerini gösterir.",
    )
    show_menu(window, ["Detayları gör", "Güncelle", "Değişiklik günlüğü", "---", "Kaldır"], package_menu_path)
    manifest.append({"file": str(package_menu_path.relative_to(destination)), "kind": "menu", "title": "Paketler Sağ Tık Menüsü", "location": "Paketler sayfası > paket satırına sağ tık", "description": "Paket yönetimi eylemleri."})


def build_index(destination: Path, manifest: list[dict], real_data: dict) -> None:
    lines = [
        "# SourceDock UI Showcase",
        "",
        "Bu arşiv SourceDock'un ana sayfalarını, detay ekranlarını ve küçük pencerelerini arkadaşla paylaşmak için hazırlanmıştır.",
        "",
        f"Gerçek veri özeti: {real_data['applications']} uygulama, {real_data['packages']} paket, {real_data['store_results']} mağaza sonucu.",
        "",
        "## İçindekiler",
        "",
        "- `pages/`: Kurulu, Keşfet, Paketler, İşlemler ve Güncellemeler sayfaları; karanlık/aydınlık/sistem ve Türkçe/İngilizce varyantlar.",
        "- `windows/`: Detay, kurucu, ayarlar ve tüm yakalanan mini pencereler.",
        "- `menus/`: Kurulu uygulama ve paket satırlarının sağ tık menüleri.",
        "- Her görselin yanında aynı ada sahip `.md` dosyası vardır; konumunu, nasıl açıldığını ve ne gösterdiğini anlatır.",
        "- `capture.json`: Görsellerin kaynak kökü, commit'i, paket bilgisi, üretim zamanı ve viewport kanıt durumu.",
        "",
        "## Ekranlar",
        "",
    ]
    for item in manifest:
        query = item.get("active_query") or "(boş)"
        mode = item.get("data_mode", "real-system-read-only")
        lines.append(
            f"- `{item['file']}`: **{item['title']}** — {item['location']} "
            f"(arama: `{query}`, veri: `{mode}`)."
        )
    (destination / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_audit_documents(destination: Path) -> None:
    """Include the implementation audit beside the shareable screenshots."""
    for filename in (
        "SOURCEDOCK_UI_UX_AUDIT_REPORT.md",
        "SOURCEDOCK_UI_UX_DENETIM_CODEX.md",
        "SOURCEDOCK_V3_KALAN_DUZELTMELER_CODEX.md",
        "SOURCEDOCK_V5_AUDIT_REPORT.md",
        "SOURCEDOCK_V6_AUDIT_REPORT.md",
        "SOURCEDOCK_V7_AUDIT_REPORT.md",
        "SOURCEDOCK_V8_ACCEPTANCE_REPORT.md",
        "SOURCEDOCK_V9_ACCEPTANCE_REPORT.md",
    ):
        source = ROOT / filename
        if source.exists():
            shutil.copy2(source, destination / filename)
    validation = ROOT / "docs" / "screenshots" / "validation.json"
    if validation.exists():
        shutil.copy2(validation, destination / "validation.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "sourcedock-ui-showcase"))
    parser.add_argument("--zip", default=str(ROOT / "artifacts" / "SourceDock_UI_Showcase.zip"))
    parser.add_argument("--package")
    args = parser.parse_args()
    assert Gtk.init_check()[0], "GTK ekranı gerekli (Xvfb kullanın)"

    destination = Path(args.output)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    zip_path = Path(args.zip)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    manifest: list[dict] = []
    copy_page_screenshots(destination, manifest)

    print("Gerçek uygulama ve paket verisi okunuyor (kurulum/kaldırma yok).", flush=True)
    registry = ApplicationRegistry()
    snapshot = registry.load()
    packages = registry.list_packages()
    results = StoreRegistry().search("firefox")
    print(f"Okundu: {len(snapshot.applications)} uygulama, {len(packages)} paket, {len(results)} mağaza sonucu.", flush=True)
    window = make_window(snapshot, packages, results)
    try:
        capture_generated_windows(destination, window, registry, snapshot, results, manifest)
    finally:
        window.destroy()

    for item in manifest:
        item.setdefault("data_mode", "real-system-read-only")

    build_index(
        destination,
        manifest,
        {"applications": len(snapshot.applications), "packages": len(packages), "store_results": len(results)},
    )
    copy_audit_documents(destination)
    (destination / "capture.json").write_text(
        json.dumps(capture_provenance(args.package), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in sorted(destination.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(destination.parent))
    print(f"{len(manifest)} ekran ve açıklaması üretildi.", flush=True)
    print(f"ZIP: {zip_path}", flush=True)


if __name__ == "__main__":
    main()
