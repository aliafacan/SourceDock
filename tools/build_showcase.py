#!/usr/bin/env python3
"""SourceDock UI showcase ZIP'i üretir.

Gerçek sistem verisini yalnızca okumak için kullanır; hiçbir kurulum, kaldırma
veya güncelleme işlemi çalıştırmaz. Ekran görüntülerinin yanında arkadaşla
paylaşılabilecek Türkçe konum ve kullanım notları üretir.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
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


def write_note(path: Path, title: str, location: str, how_to_open: str, description: str) -> None:
    path.with_suffix(".md").write_text(
        f"# {title}\n\n"
        f"- **Konum:** {location}\n"
        f"- **Açma yolu:** {how_to_open}\n"
        f"- **Bu ekran:** {description}\n",
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
    for item in reversed(stack):
        item.stop()
    window.resize(1366, 768)
    window._finish_applications_load(snapshot)
    window._finish_packages_load(packages, None)
    window.store_results = results
    window._finish_store_search(results, None)
    window._finish_updates_load(updates, snapshot.provider_errors, None)
    window.show_all()
    settle(500)
    return window


def show_menu(window: MainWindow, labels: list[str], path: Path) -> None:
    menu = Gtk.Menu()
    for label in labels:
        if label == "---":
            menu.append(Gtk.SeparatorMenuItem())
        else:
            menu.append(Gtk.MenuItem(label=label))
    menu.show_all()
    anchor = window.applications_tree
    menu.popup_at_widget(anchor, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
    capture_menu_composite(window, menu, path)
    menu.popdown()
    menu.destroy()


def copy_page_screenshots(destination: Path, manifest: list[dict]) -> None:
    page_titles = {
        "installed": ("Kurulu Uygulamalar", "Sol menü > Kurulu", "Sistemde algılanan kurulu uygulamaların listesi."),
        "discover": ("Keşfet", "Sol menü > Keşfet", "Mağaza araması, kaynak filtreleri ve uygulama sonuçları."),
        "packages": ("Paketler", "Sol menü > Paketler", "Kurulu ve kullanılabilir paketlerin tablo görünümü."),
        "operations": ("İşlemler", "Sol menü > İşlemler", "Devam eden ve tamamlanan kurulum/güncelleme işlemleri."),
        "updates": ("Güncellemeler", "Sol menü > Güncellemeler", "Seçilebilir güncellemeler, sürüm bilgileri ve toplu işlem alanı."),
    }
    for page, (title, location, description) in page_titles.items():
        for theme in ("dark", "light"):
            for language in ("tr", "en"):
                source = ROOT / "docs" / "screenshots" / f"{page}-{theme}-{language}-100-1366x768.png"
                if not source.exists():
                    continue
                target = destination / "pages" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                localized = f"{title} ({'karanlık' if theme == 'dark' else 'aydınlık'} tema, {language.upper()})"
                write_note(target, localized, location, location, description)
                manifest.append(
                    {
                        "file": str(target.relative_to(destination)),
                        "kind": "page",
                        "title": localized,
                        "location": location,
                        "description": description,
                    }
                )

    existing_titles = {
        "details": ("Kurulu Uygulama Detayı", "Kurulu > bir uygulamayı çift tıkla veya Enter", "Uygulamanın meta bilgileri, durumu ve çalıştırma/güncelleme/kaldırma eylemleri."),
        "installer": ("Yerel Paket Kurucusu", "Üst çubuk > Yerel paket aç veya bir .deb dosyasına çift tıkla", "Yerel paket dosyasının sürüm, boyut, bağımlılık ve kurulum özeti."),
        "settings": ("Ayarlar", "Üst çubuk > dişli simgesi", "Dil, tema, ölçek, güncelleme ve tercih edilen kaynak ayarları."),
    }
    for prefix, (title, location, description) in existing_titles.items():
        for theme in ("dark", "light"):
            for language in ("tr", "en"):
                source = ROOT / "docs" / "screenshots" / f"{prefix}-{theme}-{language}-100-1366x768.png"
                if not source.exists():
                    continue
                target = destination / "windows" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                localized = f"{title} ({'karanlık' if theme == 'dark' else 'aydınlık'} tema, {language.upper()})"
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

    def add(path_name, title, location, how_to_open, description):
        path = windows / path_name
        manifest.append({"file": str(path.relative_to(destination)), "kind": "window", "title": title, "location": location, "description": description})
        write_note(path, title, location, how_to_open, description)
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
    )
    store_dialog = AppDetailDialog(primary, results, set(), lambda _result: None, "tr", window)
    capture(store_dialog, store_path)
    store_dialog.destroy()

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
    )
    capture_running_dialog(window, lambda: window._ask_sudo_password(), password_path)

    firmware_path = add(
        "firmware-confirmation-dark-tr.png",
        "Firmware Güncelleme Onayı",
        "Güncellemeler > firmware satırı seçiliyken güncelle",
        "Bir firmware güncellemesini uygulamayı dene.",
        "Firmware işleminin özel riskini açıklayan onay mesajı ve iptal/tamam düğmeleri.",
    )
    capture_running_dialog(window, window._confirm_firmware_update, firmware_path)

    snap_path = add(
        "snap-classic-confirmation-dark-tr.png",
        "Snap Classic İzni Onayı",
        "Keşfet > classic yetkisi isteyen Snap kurulumu",
        "Classic confinement isteyen bir Snap uygulamasını kurmayı dene.",
        "Classic yetkisinin güvenlik etkisini açıklayan özel onay penceresi.",
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
        "- `pages/`: Kurulu, Keşfet, Paketler, İşlemler ve Güncellemeler sayfaları; karanlık/aydınlık ve Türkçe/İngilizce varyantlar.",
        "- `windows/`: Detay, kurucu, ayarlar ve tüm yakalanan mini pencereler.",
        "- `menus/`: Kurulu uygulama ve paket satırlarının sağ tık menüleri.",
        "- Her görselin yanında aynı ada sahip `.md` dosyası vardır; konumunu, nasıl açıldığını ve ne gösterdiğini anlatır.",
        "",
        "## Ekranlar",
        "",
    ]
    for item in manifest:
        lines.append(f"- `{item['file']}`: **{item['title']}** — {item['location']}.")
    (destination / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "artifacts" / "sourcedock-ui-showcase"))
    parser.add_argument("--zip", default=str(ROOT / "artifacts" / "SourceDock_UI_Showcase.zip"))
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

    build_index(
        destination,
        manifest,
        {"applications": len(snapshot.applications), "packages": len(packages), "store_results": len(results)},
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in sorted(destination.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(destination.parent))
    print(f"{len(manifest)} ekran ve açıklaması üretildi.", flush=True)
    print(f"ZIP: {zip_path}", flush=True)


if __name__ == "__main__":
    main()
