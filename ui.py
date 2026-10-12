#!/usr/bin/env python3
"""Zorin App Manager GTK arayüzü."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
import re
import shlex
import threading
import urllib.request
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]

from backend import AuthRequiredError, BackendError, SnapClassicRequiredError
from applications import (
    SOURCE_APPIMAGE,
    SOURCE_APT,
    SOURCE_FLATPAK,
    SOURCE_SNAP,
    ApplicationIssue,
    ApplicationRegistry,
    ApplicationSnapshot,
    PackageInfo,
    UnifiedApplication,
)
from store import SOURCE_FLATPAK as STORE_FLATPAK, SOURCE_SNAP as STORE_SNAP, SOURCE_APT as STORE_APT, StoreRegistry, StoreResult
from constants import APP_ICON_NAME, APP_TITLE
from i18n import t, translate_backend_message
from preferences import AppPreferences, PreferencesStore
from theme import get_theme_css


# Installed apps tree columns
_AC_ICON = 0
_AC_NAME = 1
_AC_SOURCE = 2
_AC_VERSION = 3
_AC_SIZE_KIB = 4
_AC_SIZE_STR = 5
_AC_LAST_UPDATED = 6
_AC_LOCATION = 7
_AC_APP = 8

# Store results tree columns
_SC_ICON = 0
_SC_NAME = 1
_SC_SOURCE = 2
_SC_DESCRIPTION = 3
_SC_VERSION = 4
_SC_REMOTE = 5
_SC_SIZE = 6
_SC_RESULT = 7

# Packages tree columns
_PC_NAME = 0
_PC_VERSION = 1
_PC_NEW_VERSION = 2
_PC_SIZE_KIB = 3
_PC_SIZE_STR = 4
_PC_DESCRIPTION = 5
_PC_UPGRADABLE = 6
_PC_PKG = 7

# Operations tree columns
_OC_ICON = 0
_OC_PID = 1
_OC_COMMAND = 2
_OC_PACKAGES = 3


class OperationProgressWindow(Gtk.Window):
    """Küçültülebilir işlem penceresi; ana görünüm özet, detaylar isteğe bağlı."""

    def __init__(
        self,
        title: str,
        message: str,
        parent: Gtk.Window,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> None:
        super().__init__(title=title)
        self.set_default_size(460, 190)
        self.set_resizable(True)
        self.set_deletable(True)
        self.set_skip_taskbar_hint(False)
        self.set_skip_pager_hint(False)
        self.set_decorated(True)
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self.get_style_context().add_class("icon-settings-window")
        self._done = False
        self._on_progress = on_progress
        self._download_total_kib: int | None = None
        self._download_seen_kib = 0
        self._download_seen_items = 0
        self._download_items_total: int | None = None
        self._install_items_done = 0
        self._install_items_total: int | None = None
        self._install_phase_started = False
        self._current_package = ""
        self.connect("delete-event", self._on_delete_event)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(16)
        content.set_margin_bottom(8)
        content.set_margin_start(16)
        content.set_margin_end(16)
        self.add(content)

        if message:
            msg_label = Gtk.Label()
            msg_label.set_markup(f"<b>{GLib.markup_escape_text(message)}</b>")
            msg_label.set_xalign(0)
            content.pack_start(msg_label, False, False, 0)

        self._progress = Gtk.ProgressBar()
        self._progress.set_pulse_step(0.05)
        content.pack_start(self._progress, False, False, 0)

        self._title_label = Gtk.Label(label="Hazırlanıyor...")
        self._title_label.set_xalign(0)
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(self._title_label, False, False, 0)

        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0)
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_label.get_style_context().add_class("dim-label")
        content.pack_start(self._status_label, False, False, 0)

        self._details_expander = Gtk.Expander(label="Detaylar")
        self._details_expander.set_expanded(False)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(180)
        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_monospace(True)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_buf = self._log_view.get_buffer()
        scrolled.add(self._log_view)
        self._details_expander.add(scrolled)
        content.pack_start(self._details_expander, True, True, 0)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_row.set_halign(Gtk.Align.END)
        content.pack_start(button_row, False, False, 0)

        self._minimize_btn = Gtk.Button(label="Küçült")
        self._minimize_btn.connect("clicked", lambda _button: self.iconify())
        button_row.pack_start(self._minimize_btn, False, False, 0)

        self._close_btn = Gtk.Button(label="Kapat")
        self._close_btn.get_style_context().add_class("suggested-action")
        self._close_btn.set_sensitive(False)
        self._close_btn.connect("clicked", lambda _button: self.destroy())
        button_row.pack_start(self._close_btn, False, False, 0)

        self._pulse_source: int | None = GLib.timeout_add(80, self._pulse)
        self.show_all()

    def _short_error(self, message: str) -> str:
        lowered = message.lower()
        if "lock-frontend" in lowered or "kilidi alınamadı" in lowered or "kilitlenemiyor" in lowered:
            return "APT şu anda başka bir işlem tarafından kullanılıyor. Diğer güncelleme/kurulum bitince tekrar dene."
        if "dpkg" in lowered and "configure -a" in lowered:
            return "DPKG yarım kalmış. Önce bakım işlemi gerekiyor: sudo dpkg --configure -a"
        if "access denied" in lowered or "sudo ile dene" in lowered:
            return "Yönetici izni gerekiyor."
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), message.strip())
        return first_line[:180]

    def _pulse(self) -> bool:
        self._progress.pulse()
        return True

    def _start_pulse(self) -> None:
        self._progress.set_text("")
        self._progress.set_show_text(False)
        self._progress.set_fraction(0.0)
        if self._pulse_source is None:
            self._pulse_source = GLib.timeout_add(80, self._pulse)

    def _set_activity_phase(self, title: str, status: str) -> None:
        self._start_pulse()
        self._title_label.set_text(title)
        self._status_label.set_text(status)

    def append_log(self, line: str) -> None:
        if not line.strip():
            return
        self._append_detail(line)
        if self._consume_package_progress(line):
            self._fire_progress()
            return
        percent_match = re.search(r"(\d{1,3})\s*%", line)
        if percent_match:
            self._stop_pulse()
            percent = max(0, min(100, int(percent_match.group(1))))
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            self._fire_progress()
            return
        status = self._summarize_progress_line(line)
        if status:
            self._status_label.set_text(status[:180])
            self._fire_progress()

    def _append_detail(self, line: str) -> None:
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, line.rstrip() + "\n")
        mark = self._log_buf.create_mark(None, self._log_buf.get_end_iter(), False)
        self._log_view.scroll_mark_onscreen(mark)
        self._log_buf.delete_mark(mark)

    def _consume_package_progress(self, line: str) -> bool:
        clean = re.sub(r"\s+", " ", line).strip()
        lowered = clean.lower()

        # ── Flatpak progress ─────────────────────────────────────────────────
        # Progress bar: "[======    ] 45%  12.3 MB/s 00:05 ETA"
        # or "[■■■■■         ] 45%" — flatpak uses U+25A0 block chars
        fp_bar = re.search(r"[\[|]\s*[=■▌█▇▆▅▄▃▂▁\s]*[\]|]\s*(\d{1,3})\s*%", clean)
        if fp_bar:
            percent = max(0, min(100, int(fp_bar.group(1))))
            self._stop_pulse()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            speed_match = re.search(r"(\d[\d.]*\s*(?:MB|KB|GB)/s)", clean, re.IGNORECASE)
            if speed_match:
                self._status_label.set_text(f"%{percent} — {speed_match.group(1)}")
            return True
        # "Installing app/com.obsproject.Studio/x86_64/stable"
        fp_app = re.match(r"(?:Installing|Kuruluyor)\s+app/([^/\s]+)", clean, re.IGNORECASE)
        if fp_app:
            pkg = fp_app.group(1)
            self._set_activity_phase(f"Kuruluyor: {pkg}", "Flatpak paketi açılıyor...")
            return True
        # "Installing runtime/org.freedesktop.Platform/..."
        fp_rt = re.match(r"(?:Installing|Kuruluyor)\s+runtime/([^/\s]+)", clean, re.IGNORECASE)
        if fp_rt:
            self._set_activity_phase(f"Bağımlılık: {fp_rt.group(1)}", "Çalışma ortamı kuruluyor...")
            return True
        # "Updating metadata for remote 'flathub'" / "Updating 'flathub'"
        if re.search(r"(?:updating|güncelleniyor)\s+(?:metadata\s+for\s+)?(?:remote\s+)?'?\w+'?", lowered):
            self._set_activity_phase("Depo verisi güncelleniyor", "Flatpak uzak deposu yenileniyor...")
            return True
        # "Downloading https://..."
        if lowered.startswith("downloading ") or lowered.startswith("indiriliyor "):
            url = clean.split(" ", 1)[1] if " " in clean else ""
            fname = url.rstrip("/").split("/")[-1][:60] if url else ""
            self._set_activity_phase("İndiriliyor", fname or "Flatpak verisi alınıyor...")
            return True

        # ── Snap progress ────────────────────────────────────────────────────
        # "snap-id  57%  xxx kB/s →  done"
        snap_pct = re.search(r"\b(\d{1,3})%\b", clean)
        if snap_pct and re.search(r"[kKmMgG][bB]/?s|→|snap", clean, re.IGNORECASE):
            percent = max(0, min(100, int(snap_pct.group(1))))
            self._stop_pulse()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            return True

        if lowered.startswith("apt meşgul:"):
            self._set_activity_phase("APT başka bir işlem tarafından kullanılıyor", self._summarize_apt_busy_line(clean))
            return True
        if "otomatik devam edilecek" in lowered:
            if not self._status_label.get_text().startswith("APT meşgul:"):
                self._set_activity_phase("APT kilidi bekleniyor", clean)
            return True
        if "apt kilidi boşaldı" in lowered:
            self._set_activity_phase("APT kilidi boşaldı", "İşleme devam ediliyor...")
            return True
        if "lock-frontend" in lowered or "kilidi alınamadı" in lowered or "önbellek kilidi bekleniyor" in lowered:
            self._set_activity_phase(
                "APT başka bir işlem tarafından kullanılıyor",
                "Diğer kurulum veya güncelleme bitince tekrar dene.",
            )
            return True
        summary_match = re.search(
            r"(?P<upgrade>\d+)\s+paket yükseltilecek,\s*(?P<new>\d+)\s+yeni paket kurulacak",
            lowered,
        )
        if summary_match:
            self._install_items_total = int(summary_match.group("upgrade")) + int(summary_match.group("new"))
            self._download_items_total = self._install_items_total
            self._set_activity_phase(
                "Güncelleme hazırlanıyor",
                f"{self._install_items_total} paket işlenecek.",
            )
            return True
        total_match = re.search(
            r"(?:(?P<cached_num>[0-9][0-9.,]*)\s*(?P<cached_unit>[kmgt]?b)/)?(?P<total_num>[0-9][0-9.,]*)\s*(?P<total_unit>[kmgt]?b)\s+arşiv",
            clean,
            re.IGNORECASE,
        )
        if total_match:
            if total_match.group("cached_num") and total_match.group("cached_unit"):
                # APT's "285 MB/292 MB indirilecek" means 285 MB will be downloaded
                # from a 292 MB archive set. Progress should track the amount to fetch.
                self._download_total_kib = self._human_size_to_kib(total_match.group("cached_num"), total_match.group("cached_unit"))
            else:
                self._download_total_kib = self._human_size_to_kib(total_match.group("total_num"), total_match.group("total_unit"))
            self._download_seen_kib = 0
            self._download_seen_items = 0
            self._title_label.set_text("İndirme hazırlanıyor")
            self._update_download_status()
            return True
        download_match = re.search(r"^(?:İndir|Get):\s*(\d+)\s+(.+?)\[([0-9][0-9.,]*)\s*([kmgt]?b)\]", clean, re.IGNORECASE)
        if download_match:
            index = int(download_match.group(1))
            package = self._package_name_from_apt_download(download_match.group(2))
            size_kib = self._human_size_to_kib(download_match.group(3), download_match.group(4))
            if index > self._download_seen_items:
                self._download_seen_items = index
                self._download_seen_kib += size_kib
            self._current_package = package
            self._title_label.set_text(f"İndiriliyor: {package}")
            self._update_download_status()
            return True
        select_match = re.search(r"daha önce seçili olmayan\s+(.+?)\s+paketi seçiliyor", clean, re.IGNORECASE)
        if select_match:
            package = select_match.group(1).strip()
            self._current_package = package
            self._install_phase_started = True
            self._set_activity_phase(f"Seçiliyor: {package}", "Yeni paket kuruluma hazırlanıyor...")
            return True
        prepare_match = re.search(r"paket açılacak:\s*(?:\S*/)?(?:\d+-)?([^_\s/]+)", clean, re.IGNORECASE)
        if prepare_match:
            package = prepare_match.group(1).strip()
            self._current_package = package
            self._install_phase_started = True
            self._set_activity_phase(f"Hazırlanıyor: {package}", "Paket dosyası açılmaya hazırlanıyor...")
            return True
        database_match = re.search(r"veritabanı okunuyor.*?(\d{1,3})%", lowered)
        if database_match:
            percent = max(0, min(100, int(database_match.group(1))))
            self._stop_pulse()
            self._install_phase_started = True
            self._title_label.set_text("Paket veritabanı okunuyor")
            self._status_label.set_text(f"%{percent} tamamlandı")
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            return True
        for pattern, prefix, status in (
            (r"paket açılıyor:\s*([^\s(]+)", "Kuruluyor", "Paket açılıyor..."),
            (r"ayarlanıyor:\s*([^\s(]+)", "Ayarlanıyor", "Kurulum tamamlanıyor..."),
            (r"tetikleyiciler işleniyor:\s*([^\s(]+)", "Tetikleyiciler işleniyor", "Sistem kayıtları güncelleniyor..."),
        ):
            match = re.search(pattern, clean, re.IGNORECASE)
            if match:
                self._install_phase_started = True
                self._current_package = match.group(1)
                if prefix == "Ayarlanıyor":
                    self._install_items_done = min(self._install_items_done + 1, self._install_items_total or self._install_items_done + 1)
                    if self._install_items_total:
                        status = f"{status} {self._install_items_done}/{self._install_items_total} paket"
                self._set_activity_phase(f"{prefix}: {match.group(1)}", status)
                return True
        setup = self._summarize_progress_line(clean)
        if setup and setup != clean:
            self._set_activity_phase(setup, "İşlem sürüyor...")
            return True
        return False

    def _summarize_progress_line(self, line: str) -> str:
        clean = re.sub(r"\s+", " ", line).strip()
        lowered = clean.lower()
        if not clean or lowered.startswith("warning: apt does not have") or lowered.startswith("n: "):
            return ""
        if "paket listeleri okunuyor" in lowered or "reading package lists" in lowered:
            return "Paket listeleri okunuyor..."
        if "bağımlılık ağacı" in lowered:
            return "Bağımlılıklar hesaplanıyor..."
        if "durum bilgisi" in lowered:
            return "Paket durumları okunuyor..."
        if "yükseltme hesaplanıyor" in lowered:
            return "Yükseltme hesaplanıyor..."
        if "yapacak bir şey yok" in lowered:
            return "Yapacak bir şey yok."
        if clean.startswith(("E:", "hata:", "error:")):
            return "İşlem tamamlanamadı."
        return clean

    def _summarize_install_line(self, line: str) -> str:
        clean = re.sub(r"\s+", " ", line).strip()
        lowered = clean.lower()
        if not clean or lowered.startswith("n: "):
            return ""
        if "dkms:" in lowered or "building module" in lowered:
            suffix = f" ({self._current_package})" if self._current_package else ""
            return f"Çekirdek modülleri derleniyor{suffix}..."
        if lowered.startswith("cleaning build area"):
            return "Derleme alanı temizleniyor..."
        if lowered.startswith("signing module") or "sign command" in lowered:
            return "Çekirdek modülleri imzalanıyor..."
        if lowered.startswith("running module version sanity check"):
            return "Modül sürümü kontrol ediliyor..."
        if lowered.startswith("installing to ") or " - installing to " in lowered:
            return "Modül sisteme kuruluyor..."
        if lowered.startswith("depmod"):
            return "Modül bağımlılıkları güncelleniyor..."
        if lowered.startswith("applying patch"):
            return "Modül yamaları uygulanıyor..."
        if lowered.startswith("update-initramfs") or "initramfs" in lowered:
            return "Başlatma imajı güncelleniyor..."
        if lowered.startswith("generating grub") or "grub" in lowered:
            return "Önyükleyici kayıtları güncelleniyor..."
        if "tetikleyiciler işleniyor" in lowered:
            return "Sistem kayıtları güncelleniyor..."
        return ""

    def _summarize_apt_busy_line(self, line: str) -> str:
        lower = line.lower()
        packages = self._packages_from_apt_command(line)
        if packages:
            first = packages[0]
            rest = len(packages) - 1
            action = "güncelleniyor"
            if " remove " in lower or " purge " in lower:
                action = "kaldırılıyor"
            elif " install " in lower and "--only-upgrade" not in lower:
                action = "kuruluyor"
            suffix = f" +{rest} paket" if rest > 0 else ""
            return f"APT meşgul: {first}{suffix} {action}."
        if "unattended-upgrade" in lower:
            return "APT meşgul: otomatik sistem güncellemesi çalışıyor."
        pid_match = re.search(r"pid\s+\d+:\s*([^;]+)", line, re.IGNORECASE)
        if pid_match:
            command = pid_match.group(1).strip()
            return f"APT meşgul: {command[:120]}"
        return "APT meşgul: başka bir paket işlemi çalışıyor."

    def _packages_from_apt_command(self, line: str) -> list[str]:
        matches = re.findall(r"(?:apt-get|apt|nala)\s+(.+?)(?:;|$)", line)
        ignore_tokens = {
            "sudo", "-n", "-s", "-y", "-q", "install", "upgrade", "full-upgrade",
            "dist-upgrade", "remove", "purge", "autoremove", "--only-upgrade",
            "--", "apt-get", "apt", "nala",
        }
        packages: list[str] = []
        for match in matches:
            try:
                tokens = shlex.split(match)
            except ValueError:
                tokens = match.split()
            skip_next = False
            for token in tokens:
                if skip_next:
                    skip_next = False
                    continue
                if token == "-o":
                    skip_next = True
                    continue
                if token.startswith("-") or "=" in token or token in ignore_tokens:
                    continue
                if "/" in token or token.startswith("PID"):
                    continue
                if token not in packages:
                    packages.append(token)
        return packages

    def _update_download_status(self) -> None:
        if not self._download_total_kib:
            return
        self._stop_pulse()
        fraction = max(0.0, min(1.0, self._download_seen_kib / self._download_total_kib))
        self._progress.set_fraction(fraction)
        percent = int(fraction * 100)
        self._progress.set_text(f"%{percent}")
        self._progress.set_show_text(True)
        if percent >= 100:
            self._title_label.set_text("İndirme tamamlandı")
            self._status_label.set_text(
                f"{self._format_kib(min(self._download_seen_kib, self._download_total_kib))} / {self._format_kib(self._download_total_kib)} - kurulum hazırlanıyor..."
            )
        else:
            item_part = ""
            if self._download_items_total:
                item_part = f" · {min(self._download_seen_items, self._download_items_total)}/{self._download_items_total} paket"
            self._status_label.set_text(
                f"{self._format_kib(min(self._download_seen_kib, self._download_total_kib))} / {self._format_kib(self._download_total_kib)}{item_part}"
            )

    def _package_name_from_apt_download(self, body: str) -> str:
        tokens = body.split()
        arch_tokens = {"all", "amd64", "arm64", "i386", "armhf"}
        for index in range(len(tokens) - 2, 1, -1):
            if tokens[index] in arch_tokens and tokens[index - 1] not in arch_tokens:
                return tokens[index - 1]
        return "paket"

    def _human_size_to_kib(self, number: str, unit: str) -> int:
        normalized = number
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        elif re.match(r"^\d{1,3}(\.\d{3})+$", normalized):
            normalized = normalized.replace(".", "")
        value = float(normalized)
        multipliers = {"b": 1 / 1024, "kb": 1, "mb": 1024, "gb": 1024 * 1024, "tb": 1024 * 1024 * 1024}
        return max(1, int(value * multipliers.get(unit.lower(), 1)))

    def _format_kib(self, kib: int) -> str:
        if kib >= 1024 * 1024:
            return f"{kib / (1024 * 1024):.1f} GB"
        if kib >= 1024:
            return f"{kib / 1024:.1f} MB"
        return f"{kib} KB"

    def _stop_pulse(self) -> None:
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None

    def _fire_progress(self) -> None:
        if not self._on_progress:
            return
        fraction = self._progress.get_fraction()
        label = self._title_label.get_text()
        self._on_progress(fraction, label)

    def finish(self, success: bool, message: str) -> None:
        self._done = True
        self._stop_pulse()
        self._progress.set_fraction(1.0 if success else 0.0)
        self._progress.set_text("%100" if success else "")
        self._progress.set_show_text(success)
        color = "#59d38c" if success else "#ff7f7f"
        self._title_label.set_text("Tamamlandı" if success else "İşlem tamamlanamadı")
        status = message if success else self._short_error(message)
        self._status_label.set_markup(f'<span foreground="{color}" weight="bold">{GLib.markup_escape_text(status)}</span>')
        self._append_detail(message)
        self._fire_progress()
        self._close_btn.set_sensitive(True)
        self._close_btn.grab_focus()
        if success:
            GLib.timeout_add(2000, self._auto_close)

    def _auto_close(self) -> bool:
        if self._done:
            self.destroy()
        return False

    def _on_delete_event(self, _window: Gtk.Window, _event) -> bool:
        if not self._done:
            self.iconify()
            return True
        return False


class AppDetailDialog(Gtk.Dialog):
    """Uygulama detay, ekran görüntüsü ve kurulum diyaloğu."""

    def __init__(
        self,
        primary_result: StoreResult,
        all_results: list[StoreResult],
        installed_package_ids: set[str],
        install_callback: Callable[[StoreResult], None],
        language: str,
        parent: Gtk.Window,
    ) -> None:
        super().__init__(
            title=primary_result.name,
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self.set_default_size(740, 580)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")

        self._primary = primary_result
        self._installed_ids = installed_package_ids
        self._install_callback = install_callback
        self._language = language
        self._selected_result = primary_result
        self._source_combo: Gtk.ComboBoxText | None = None

        name_lower = primary_result.name.lower()
        seen_sources: set[str] = {primary_result.source}
        self._alternates: list[StoreResult] = []
        for r in all_results:
            if r.name.lower() == name_lower and r.source not in seen_sources:
                self._alternates.append(r)
                seen_sources.add(r.source)

        # Find Flatpak app_id from primary or alternates (for screenshots)
        if primary_result.source == STORE_FLATPAK:
            self._flatpak_app_id: str | None = primary_result.app_id
        else:
            alt_fp = next((a for a in self._alternates if a.source == STORE_FLATPAK), None)
            self._flatpak_app_id = alt_fp.app_id if alt_fp else None

        self._build_content()
        self.connect("response", lambda _d, _r: self.destroy())
        self.show_all()

        if self._flatpak_app_id:
            threading.Thread(target=self._load_screenshots_async, daemon=True).start()

    def _build_content(self) -> None:
        content = self.get_content_area()
        content.set_spacing(0)

        outer_scroll = Gtk.ScrolledWindow()
        outer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer_scroll.set_min_content_height(420)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(16)

        # Header: icon + name + meta
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)

        self._icon_image = Gtk.Image()
        self._icon_image.set_pixel_size(96)
        self._icon_image.set_valign(Gtk.Align.START)
        self._load_icon(self._primary, 96)
        header_box.pack_start(self._icon_image, False, False, 0)

        info_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        info_vbox.set_valign(Gtk.Align.CENTER)

        name_label = Gtk.Label()
        name_label.set_markup(
            f'<span size="xx-large" weight="bold">{GLib.markup_escape_text(self._primary.name)}</span>'
        )
        name_label.set_xalign(0)
        name_label.set_line_wrap(True)
        info_vbox.pack_start(name_label, False, False, 0)

        self._meta_base_parts: list[str] = [self._primary.source.capitalize(), self._primary.remote]
        if self._primary.version:
            self._meta_base_parts.append(f"v{self._primary.version}")
        self._meta_size_str: str = self._primary.download_size_str or ""
        meta_display = list(self._meta_base_parts)
        if self._meta_size_str:
            meta_display.append(self._meta_size_str)
        self._meta_label = Gtk.Label(label="  ·  ".join(meta_display))
        self._meta_label.set_xalign(0)
        self._meta_label.get_style_context().add_class("dim-label")
        info_vbox.pack_start(self._meta_label, False, False, 0)

        if self._alternates:
            source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            source_row.set_margin_top(4)
            lbl = Gtk.Label(label=t(self._language, "store_detail_source"))
            lbl.set_xalign(0)
            source_row.pack_start(lbl, False, False, 0)

            self._source_combo = Gtk.ComboBoxText()
            self._source_combo.append(
                self._primary.source,
                f"{self._primary.source.capitalize()} ({self._primary.remote})",
            )
            for alt in self._alternates:
                self._source_combo.append(
                    alt.source,
                    f"{alt.source.capitalize()} ({alt.remote})",
                )
            self._source_combo.set_active_id(self._primary.source)
            self._source_combo.connect("changed", self._on_source_changed)
            source_row.pack_start(self._source_combo, False, False, 0)
            info_vbox.pack_start(source_row, False, False, 0)

        header_box.pack_start(info_vbox, True, True, 0)
        main_box.pack_start(header_box, False, False, 0)

        # Screenshots section (when any Flatpak version is available)
        if self._flatpak_app_id:
            self._screenshots_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

            self._screenshots_status_label = Gtk.Label()
            self._screenshots_status_label.set_xalign(0)
            self._screenshots_status_label.get_style_context().add_class("dim-label")
            self._screenshots_status_label.set_text(t(self._language, "store_screenshots_loading"))
            self._screenshots_box.pack_start(self._screenshots_status_label, False, False, 0)

            self._screenshots_scroll = Gtk.ScrolledWindow()
            self._screenshots_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            self._screenshots_scroll.set_min_content_height(275)
            self._screenshots_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self._screenshots_scroll.add(self._screenshots_inner)
            self._screenshots_scroll.set_no_show_all(True)
            self._screenshots_box.pack_start(self._screenshots_scroll, False, False, 0)

            main_box.pack_start(self._screenshots_box, False, False, 0)

        if self._primary.description:
            desc_label = Gtk.Label(label=self._primary.description)
            desc_label.set_xalign(0)
            desc_label.set_line_wrap(True)
            desc_label.set_max_width_chars(80)
            main_box.pack_start(desc_label, False, False, 0)

        outer_scroll.add(main_box)
        content.pack_start(outer_scroll, True, True, 0)

        # Bottom action bar
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_box.set_margin_start(24)
        action_box.set_margin_end(24)
        action_box.set_margin_top(8)
        action_box.set_margin_bottom(16)

        close_btn = Gtk.Button(label=t(self._language, "dialog_close"))
        close_btn.connect("clicked", lambda _b: self.response(Gtk.ResponseType.CLOSE))
        action_box.pack_end(close_btn, False, False, 0)

        open_btn = Gtk.Button(label=t(self._language, "store_open_external"))
        open_btn.connect("clicked", self._on_open_online)
        action_box.pack_start(open_btn, False, False, 0)

        is_installed = self._primary.app_id in self._installed_ids
        self._install_btn = Gtk.Button()
        if is_installed:
            self._install_btn.set_label(t(self._language, "store_installed_badge"))
            self._install_btn.set_sensitive(False)
        else:
            self._install_btn.set_label(t(self._language, "store_install_btn"))
            self._install_btn.get_style_context().add_class("suggested-action")
        self._install_btn.connect("clicked", self._on_install_clicked)
        action_box.pack_end(self._install_btn, False, False, 0)

        content.pack_start(action_box, False, False, 0)

    def _load_icon(self, result: StoreResult, size: int) -> None:
        if result.icon_path and os.path.exists(result.icon_path):
            try:
                raw = GdkPixbuf.Pixbuf.new_from_file(result.icon_path)
                pixbuf = raw.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
                self._icon_image.set_from_pixbuf(pixbuf)
                return
            except Exception:
                pass
        theme = Gtk.IconTheme.get_default()
        candidates = [result.app_id]
        parts = result.app_id.rsplit(".", 1)
        if len(parts) > 1:
            candidates.append(parts[-1].lower())
        candidates.append("application-x-executable")
        for icon_name in candidates:
            try:
                pixbuf = theme.load_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                self._icon_image.set_from_pixbuf(pixbuf)
                return
            except Exception:
                pass
        self._icon_image.set_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)

    def _on_source_changed(self, combo: Gtk.ComboBoxText) -> None:
        source_id = combo.get_active_id()
        if source_id == self._primary.source:
            self._selected_result = self._primary
        else:
            for alt in self._alternates:
                if alt.source == source_id:
                    self._selected_result = alt
                    break
        is_installed = self._selected_result.app_id in self._installed_ids
        if is_installed:
            self._install_btn.set_label(t(self._language, "store_installed_badge"))
            self._install_btn.set_sensitive(False)
            self._install_btn.get_style_context().remove_class("suggested-action")
        else:
            self._install_btn.set_label(t(self._language, "store_install_btn"))
            self._install_btn.set_sensitive(True)
            self._install_btn.get_style_context().add_class("suggested-action")

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        result = self._selected_result
        self.destroy()
        self._install_callback(result)

    def _on_open_online(self, _button: Gtk.Button) -> None:
        result = self._selected_result
        if result.source == STORE_FLATPAK:
            url = f"https://flathub.org/apps/{result.app_id}"
        else:
            url = f"https://snapcraft.io/{result.app_id}"
        try:
            Gtk.show_uri(None, url, 0)
        except Exception:
            pass

    def _load_screenshots_async(self) -> None:
        try:
            url = f"https://flathub.org/api/v2/appstream/{self._flatpak_app_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "ZorinAppManager/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # Fetch download size from summary endpoint (more reliable than flatpak search)
            if not self._meta_size_str:
                try:
                    summary_url = f"https://flathub.org/api/v2/summary/{self._flatpak_app_id}"
                    sum_req = urllib.request.Request(summary_url, headers={"User-Agent": "ZorinAppManager/1.0"})
                    with urllib.request.urlopen(sum_req, timeout=8) as sum_resp:
                        summary = json.loads(sum_resp.read().decode("utf-8"))
                    size_bytes = int(summary.get("download_size", 0))
                    if size_bytes > 0:
                        if size_bytes >= 1024 ** 3:
                            size_str = f"{size_bytes / 1024 ** 3:.1f} GiB"
                        elif size_bytes >= 1024 ** 2:
                            size_str = f"{size_bytes / 1024 ** 2:.1f} MiB"
                        elif size_bytes >= 1024:
                            size_str = f"{size_bytes / 1024:.0f} KiB"
                        else:
                            size_str = f"{size_bytes} B"
                        GLib.idle_add(self._update_meta_size, size_str)
                except Exception:
                    pass

            screenshots = data.get("screenshots", [])
            img_urls: list[str] = []
            for shot in screenshots[:6]:
                sizes = shot.get("sizes", [])
                if not sizes:
                    continue
                # width/height arrive as strings from the API; filter out _orig (huge) entries
                def _w(s: dict) -> int:
                    try:
                        return int(s.get("width", 0))
                    except (ValueError, TypeError):
                        return 0
                usable = [s for s in sizes if 400 <= _w(s) <= 1600]
                pool = usable or sizes
                # prefer ~1248px width
                best = min(pool, key=lambda s: abs(_w(s) - 1248))
                src = best.get("src", "")
                if src and not src.endswith("_orig.png") and not src.endswith("_orig.jpg"):
                    img_urls.append(src)
            if img_urls:
                GLib.idle_add(self._fetch_screenshot_images, img_urls)
            else:
                GLib.idle_add(self._on_screenshots_done, [])
        except Exception:
            GLib.idle_add(self._on_screenshots_done, [])

    def _update_meta_size(self, size_str: str) -> bool:
        if not hasattr(self, "_meta_label"):
            return False
        self._meta_size_str = size_str
        parts = list(self._meta_base_parts)
        parts.append(size_str)
        self._meta_label.set_text("  ·  ".join(parts))
        return False

    def _fetch_screenshot_images(self, urls: list[str]) -> bool:
        def _worker() -> None:
            pixbufs: list[GdkPixbuf.Pixbuf] = []
            for url in urls:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "ZorinAppManager/1.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = resp.read()
                    loader = GdkPixbuf.PixbufLoader.new()
                    loader.write(data)
                    loader.close()
                    pb = loader.get_pixbuf()
                    if pb:
                        h = 260
                        w = max(1, int(pb.get_width() * h / pb.get_height()))
                        pixbufs.append(pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR))
                except Exception:
                    pass
            GLib.idle_add(self._on_screenshots_done, pixbufs)

        threading.Thread(target=_worker, daemon=True).start()
        return False

    def _on_screenshots_done(self, pixbufs: list) -> bool:
        if not hasattr(self, "_screenshots_status_label"):
            return False
        if not pixbufs:
            self._screenshots_status_label.set_text(t(self._language, "store_screenshots_none"))
            return False
        self._screenshots_status_label.set_text("")
        for pb in pixbufs:
            img = Gtk.Image.new_from_pixbuf(pb)
            self._screenshots_inner.pack_start(img, False, False, 0)
        self._screenshots_inner.show_all()
        self._screenshots_scroll.show()
        return False


class AppManagerWindow(Gtk.Window):
    def __init__(self, preferences_store: PreferencesStore):
        self.preferences_store = preferences_store
        self.preferences = preferences_store.load()
        super().__init__(title=APP_TITLE)

        self.application_registry = ApplicationRegistry()
        self.store_registry = StoreRegistry()

        # Installed apps state
        self.applications: list[UnifiedApplication] = []
        self.application_issues: list[ApplicationIssue] = []
        self.application_provider_errors: list[str] = []
        self.application_filter_source = "all"
        self.application_filter_category = "__all__"
        self.application_search_text = ""
        self.applications_loading = False
        self.applications_busy = False
        self.application_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self.filtered_applications: list[UnifiedApplication] = []

        # Store state
        self.store_results: list[StoreResult] = []
        self.store_filter_source = "all"
        self.store_busy = False
        self.store_filter_buttons: dict[str, Gtk.ToggleButton] = {}
        self.installed_package_ids: set[str] = set()
        self._icon_pixbuf_cache: dict[str, GdkPixbuf.Pixbuf | None] = {}

        # Active in-app operations (store installs, app updates)
        # key → {"command": str, "base_summary": str, "display_summary": str,
        #         "pixbuf": pixbuf|None, "row_ref": TreeRowReference|None}
        self._active_ops: dict[str, dict] = {}
        self._active_op_seq = 0

        # Packages tab state
        self.packages: list[PackageInfo] = []
        self.packages_loading = False
        self.packages_search_text = ""
        self.packages_filter_upgradable = False

        self.css_provider = Gtk.CssProvider()
        self.set_default_size(900, 680)
        self._apply_window_icon()
        self.set_border_width(16)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(True)
        self.get_style_context().add_class("icon-settings-window")
        self.connect("destroy", Gtk.main_quit)

        self._build_ui()
        self._apply_theme()
        self._refresh_texts()
        self._setup_keyboard_shortcuts()
        self.reload_applications_async()

    def _apply_window_icon(self) -> None:
        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(APP_ICON_NAME):
            self.set_icon_name(APP_ICON_NAME)
            return
        # Icon cache henüz güncellenmemişse kurulu dosyadan yükle
        for path in (
            f"/usr/share/icons/hicolor/128x128/apps/{APP_ICON_NAME}.png",
            f"/usr/share/icons/hicolor/256x256/apps/{APP_ICON_NAME}.png",
            f"/usr/share/icons/hicolor/48x48/apps/{APP_ICON_NAME}.png",
        ):
            if os.path.exists(path):
                try:
                    self.set_icon_from_file(path)
                    return
                except Exception:
                    pass
        self.set_icon_name(APP_ICON_NAME)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(vbox)

        self.pages = Gtk.Notebook()
        self.pages.set_show_tabs(True)
        self.pages.set_show_border(False)
        self.pages.set_scrollable(True)
        self.pages.set_tab_pos(Gtk.PositionType.TOP)
        vbox.pack_start(self.pages, True, True, 0)

        self.settings_btn = Gtk.Button()
        self.settings_btn.get_style_context().add_class("header-action")
        self.settings_btn.connect("clicked", self.on_open_settings)
        self.settings_btn.set_valign(Gtk.Align.CENTER)
        self.settings_btn.show()
        self.pages.set_action_widget(self.settings_btn, Gtk.PackType.END)

        self.installed_tab_label = Gtk.Label()
        installed_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(installed_page, self.installed_tab_label)

        self.store_tab_label = Gtk.Label()
        store_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(store_page, self.store_tab_label)

        self.packages_tab_label = Gtk.Label()
        packages_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(packages_page, self.packages_tab_label)

        self.operations_tab_label = Gtk.Label(label="İşlemler")
        operations_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.pages.append_page(operations_page, self.operations_tab_label)

        self._build_installed_page(installed_page)
        self._build_store_page(store_page)
        self._build_packages_page(packages_page)
        self._build_operations_page(operations_page)
        self.pages.connect("switch-page", self._on_notebook_switch_page)
        self.pages.set_current_page(0)
        self.show_all()

    def _build_installed_page(self, container: Gtk.Box) -> None:
        self.applications_title_label = Gtk.Label()
        self.applications_title_label.set_xalign(0)
        container.pack_start(self.applications_title_label, False, False, 0)

        self.applications_subtitle_label = Gtk.Label()
        self.applications_subtitle_label.set_xalign(0)
        self.applications_subtitle_label.set_line_wrap(True)
        self.applications_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.applications_subtitle_label, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        container.pack_start(toolbar, False, False, 0)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.pack_start(search_row, False, False, 0)

        self.applications_search_entry = Gtk.SearchEntry()
        self.applications_search_entry.set_hexpand(True)
        self.applications_search_entry.connect("search-changed", self.on_applications_search_changed)
        search_row.pack_start(self.applications_search_entry, True, True, 0)

        self.applications_refresh_btn = Gtk.Button()
        self.applications_refresh_btn.connect("clicked", self.on_reload_applications)
        search_row.pack_start(self.applications_refresh_btn, False, False, 0)

        self.applications_check_updates_btn = Gtk.Button()
        self.applications_check_updates_btn.connect("clicked", self.on_check_for_updates)
        search_row.pack_start(self.applications_check_updates_btn, False, False, 0)

        self.applications_update_all_btn = Gtk.Button()
        self.applications_update_all_btn.get_style_context().add_class("suggested-action")
        self.applications_update_all_btn.connect("clicked", self.on_update_all_applications)
        search_row.pack_start(self.applications_update_all_btn, False, False, 0)

        self.applications_export_btn = Gtk.Button()
        self.applications_export_btn.connect("clicked", self.on_export_application_list)
        search_row.pack_start(self.applications_export_btn, False, False, 0)

        self.applications_add_appimage_btn = Gtk.Button()
        self.applications_add_appimage_btn.connect("clicked", self.on_add_appimage)
        search_row.pack_start(self.applications_add_appimage_btn, False, False, 0)

        # Source + category filter row
        filter_outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_outer.set_valign(Gtk.Align.CENTER)
        toolbar.pack_start(filter_outer, False, False, 0)

        for source in ("all", "updates", SOURCE_APT, SOURCE_FLATPAK, SOURCE_SNAP, SOURCE_APPIMAGE):
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_application_filter_toggled, source)
            filter_outer.pack_start(button, False, False, 0)
            self.application_filter_buttons[source] = button
        self.application_filter_buttons["all"].set_active(True)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(6)
        sep.set_margin_end(6)
        filter_outer.pack_start(sep, False, False, 0)

        self.applications_category_label = Gtk.Label()
        self.applications_category_label.set_valign(Gtk.Align.CENTER)
        self.applications_category_label.get_style_context().add_class("dim-label")
        filter_outer.pack_start(self.applications_category_label, False, False, 0)

        self.applications_category_combo = Gtk.ComboBoxText()
        self.applications_category_combo.set_valign(Gtk.Align.CENTER)
        self.applications_category_combo.set_size_request(150, -1)
        self.applications_category_combo.append("__all__", "")
        self.applications_category_combo.set_active(0)
        self.applications_category_combo.connect("changed", self._on_category_filter_changed)
        filter_outer.pack_start(self.applications_category_combo, False, False, 0)

        self.applications_summary_label = Gtk.Label()
        self.applications_summary_label.set_xalign(0)
        self.applications_summary_label.get_style_context().add_class("dim-label")
        container.pack_start(self.applications_summary_label, False, False, 0)

        self.applications_store = Gtk.ListStore(
            GdkPixbuf.Pixbuf,
            str,
            str,
            str,
            int,
            str,
            str,
            str,
            GObject.TYPE_PYOBJECT,
        )
        self.applications_tree = Gtk.TreeView(model=self.applications_store)
        self.applications_tree.set_headers_visible(True)
        self.applications_tree.set_activate_on_single_click(False)
        self.applications_tree.set_enable_search(False)
        self.applications_tree.set_rubber_banding(False)
        self.applications_tree.get_style_context().add_class("applications-tree")
        self.applications_tree.connect("row-activated", self.on_application_tree_activated)
        self.applications_tree.connect("button-press-event", self.on_application_tree_button_press)

        selection = self.applications_tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.connect("changed", self.on_application_selection_changed)

        app_col = Gtk.TreeViewColumn()
        self.applications_tree_col_app = app_col
        icon_renderer = Gtk.CellRendererPixbuf()
        icon_renderer.set_property("xpad", 4)
        name_renderer = Gtk.CellRendererText()
        name_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        app_col.pack_start(icon_renderer, False)
        app_col.pack_start(name_renderer, True)
        app_col.add_attribute(icon_renderer, "pixbuf", _AC_ICON)
        app_col.add_attribute(name_renderer, "text", _AC_NAME)
        app_col.set_sort_column_id(_AC_NAME)
        app_col.set_resizable(True)
        app_col.set_expand(True)
        app_col.set_min_width(180)
        self.applications_tree.append_column(app_col)

        source_renderer = Gtk.CellRendererText()
        source_col = Gtk.TreeViewColumn()
        self.applications_tree_col_source = source_col
        source_col.pack_start(source_renderer, True)
        source_col.add_attribute(source_renderer, "text", _AC_SOURCE)
        source_col.set_sort_column_id(_AC_SOURCE)
        source_col.set_resizable(True)
        source_col.set_fixed_width(90)
        self.applications_tree.append_column(source_col)

        version_renderer = Gtk.CellRendererText()
        version_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        version_col = Gtk.TreeViewColumn()
        self.applications_tree_col_version = version_col
        version_col.pack_start(version_renderer, True)
        version_col.add_attribute(version_renderer, "text", _AC_VERSION)
        version_col.set_sort_column_id(_AC_VERSION)
        version_col.set_resizable(True)
        version_col.set_fixed_width(100)
        self.applications_tree.append_column(version_col)

        size_renderer = Gtk.CellRendererText()
        size_col = Gtk.TreeViewColumn()
        self.applications_tree_col_size = size_col
        size_col.pack_start(size_renderer, True)
        size_col.add_attribute(size_renderer, "text", _AC_SIZE_STR)
        size_col.set_sort_column_id(_AC_SIZE_KIB)
        size_col.set_resizable(True)
        size_col.set_fixed_width(90)
        self.applications_tree.append_column(size_col)

        date_renderer = Gtk.CellRendererText()
        date_col = Gtk.TreeViewColumn()
        self.applications_tree_col_date = date_col
        date_col.pack_start(date_renderer, True)
        date_col.add_attribute(date_renderer, "text", _AC_LAST_UPDATED)
        date_col.set_sort_column_id(_AC_LAST_UPDATED)
        date_col.set_resizable(True)
        date_col.set_fixed_width(130)
        self.applications_tree.append_column(date_col)

        location_renderer = Gtk.CellRendererText()
        location_renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        location_col = Gtk.TreeViewColumn()
        self.applications_tree_col_location = location_col
        location_col.pack_start(location_renderer, True)
        location_col.add_attribute(location_renderer, "text", _AC_LOCATION)
        location_col.set_sort_column_id(_AC_LOCATION)
        location_col.set_resizable(True)
        location_col.set_expand(True)
        location_col.set_min_width(120)
        self.applications_tree.append_column(location_col)

        apps_scroller = Gtk.ScrolledWindow()
        apps_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        apps_scroller.add(self.applications_tree)
        container.pack_start(apps_scroller, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        self.applications_launch_btn = Gtk.Button()
        self.applications_launch_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_launch_application))
        action_bar.pack_start(self.applications_launch_btn, False, False, 0)

        self.applications_action_update_btn = Gtk.Button()
        self.applications_action_update_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_update_application))
        action_bar.pack_start(self.applications_action_update_btn, False, False, 0)

        self.applications_action_location_btn = Gtk.Button()
        self.applications_action_location_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_open_application_location))
        action_bar.pack_start(self.applications_action_location_btn, False, False, 0)

        self.applications_permissions_btn = Gtk.Button()
        self.applications_permissions_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_permissions))
        action_bar.pack_start(self.applications_permissions_btn, False, False, 0)

        self.applications_rollback_btn = Gtk.Button()
        self.applications_rollback_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_flatpak_rollback))
        action_bar.pack_start(self.applications_rollback_btn, False, False, 0)

        self.applications_changelog_btn = Gtk.Button()
        self.applications_changelog_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_show_changelog))
        action_bar.pack_start(self.applications_changelog_btn, False, False, 0)

        self.applications_action_remove_btn = Gtk.Button()
        self.applications_action_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_action_remove_btn.connect("clicked", lambda _b: self._on_selected_app_action(self.on_remove_application))
        action_bar.pack_start(self.applications_action_remove_btn, False, False, 0)

        self.applications_bulk_remove_btn = Gtk.Button()
        self.applications_bulk_remove_btn.get_style_context().add_class("outline-danger")
        self.applications_bulk_remove_btn.connect("clicked", self.on_bulk_remove_applications)
        action_bar.pack_start(self.applications_bulk_remove_btn, False, False, 0)

        self.applications_export_selected_btn = Gtk.Button()
        self.applications_export_selected_btn.connect("clicked", self._on_export_selected_applications)
        self.applications_export_selected_btn.set_sensitive(False)
        action_bar.pack_start(self.applications_export_selected_btn, False, False, 0)

        for btn in (
            self.applications_launch_btn,
            self.applications_action_update_btn,
            self.applications_action_location_btn,
            self.applications_action_remove_btn,
            self.applications_permissions_btn,
            self.applications_rollback_btn,
            self.applications_changelog_btn,
            self.applications_bulk_remove_btn,
        ):
            btn.set_sensitive(False)

        self.applications_diagnostics_expander = Gtk.Expander()
        self.applications_diagnostics_expander.get_style_context().add_class("diagnostics-expander")
        diagnostics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        diagnostics_box.set_border_width(8)
        self.applications_diagnostics_label = Gtk.Label()
        self.applications_diagnostics_label.set_xalign(0)
        self.applications_diagnostics_label.set_line_wrap(True)
        self.applications_diagnostics_label.get_style_context().add_class("dim-label")
        diagnostics_box.pack_start(self.applications_diagnostics_label, False, False, 0)
        self.applications_diagnostics_list = Gtk.ListBox()
        self.applications_diagnostics_list.set_selection_mode(Gtk.SelectionMode.NONE)
        diagnostics_box.pack_start(self.applications_diagnostics_list, False, False, 0)

        maintenance_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        maintenance_row.set_margin_top(4)
        self.applications_flatpak_cleanup_btn = Gtk.Button()
        self.applications_flatpak_cleanup_btn.connect("clicked", self.on_flatpak_cleanup)
        maintenance_row.pack_start(self.applications_flatpak_cleanup_btn, False, False, 0)
        diagnostics_box.pack_start(maintenance_row, False, False, 0)

        self.applications_diagnostics_expander.add(diagnostics_box)
        container.pack_start(self.applications_diagnostics_expander, False, False, 0)

        self.applications_status = Gtk.Label()
        self.applications_status.set_xalign(0)
        self.applications_status.set_line_wrap(True)
        container.pack_start(self.applications_status, False, False, 0)

    def _build_store_page(self, container: Gtk.Box) -> None:
        self.store_title_label = Gtk.Label()
        self.store_title_label.set_xalign(0)
        container.pack_start(self.store_title_label, False, False, 0)

        self.store_subtitle_label = Gtk.Label()
        self.store_subtitle_label.set_xalign(0)
        self.store_subtitle_label.set_line_wrap(True)
        self.store_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.store_subtitle_label, False, False, 0)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.pack_start(search_row, False, False, 0)

        self.store_search_entry = Gtk.SearchEntry()
        self.store_search_entry.set_hexpand(True)
        self.store_search_entry.connect("activate", self.on_store_search)
        search_row.pack_start(self.store_search_entry, True, True, 0)

        self.store_search_btn = Gtk.Button()
        self.store_search_btn.get_style_context().add_class("suggested-action")
        self.store_search_btn.connect("clicked", self.on_store_search)
        search_row.pack_start(self.store_search_btn, False, False, 0)

        filter_row = Gtk.FlowBox()
        filter_row.set_selection_mode(Gtk.SelectionMode.NONE)
        filter_row.set_column_spacing(6)
        filter_row.set_row_spacing(6)
        filter_row.set_max_children_per_line(10)
        container.pack_start(filter_row, False, False, 0)
        for source in ("all", STORE_FLATPAK, STORE_SNAP, STORE_APT):
            button = Gtk.ToggleButton()
            button.get_style_context().add_class("filter-chip")
            button.connect("toggled", self.on_store_filter_toggled, source)
            filter_row.add(button)
            self.store_filter_buttons[source] = button
        self.store_filter_buttons["all"].set_active(True)

        # Results tree (full height) — TreeStore for parent-child grouping
        self.store_results_store = Gtk.TreeStore(
            GdkPixbuf.Pixbuf,      # _SC_ICON
            str,                   # _SC_NAME
            str,                   # _SC_SOURCE
            str,                   # _SC_DESCRIPTION
            str,                   # _SC_VERSION
            str,                   # _SC_REMOTE
            str,                   # _SC_SIZE
            GObject.TYPE_PYOBJECT, # _SC_RESULT
        )
        self.store_tree = Gtk.TreeView(model=self.store_results_store)
        self.store_tree.set_headers_visible(True)
        self.store_tree.set_enable_search(False)
        self.store_tree.set_rubber_banding(False)
        self.store_tree.set_show_expanders(True)
        self.store_tree.connect("row-activated", self.on_store_row_activated)

        store_sel = self.store_tree.get_selection()
        store_sel.set_mode(Gtk.SelectionMode.SINGLE)
        store_sel.connect("changed", self.on_store_result_selected)

        # Column: icon + name (also carries the tree expander)
        app_col = Gtk.TreeViewColumn()
        self.store_tree_col_name = app_col
        icon_rend = Gtk.CellRendererPixbuf()
        icon_rend.set_property("xpad", 4)
        name_rend = Gtk.CellRendererText()
        name_rend.set_property("ellipsize", Pango.EllipsizeMode.END)
        app_col.pack_start(icon_rend, False)
        app_col.pack_start(name_rend, True)
        app_col.add_attribute(icon_rend, "pixbuf", _SC_ICON)
        app_col.add_attribute(name_rend, "text", _SC_NAME)

        def _name_cell_data(_col, cell, model, it, _d):
            cell.set_property("style", Pango.Style.ITALIC if model.iter_parent(it) else Pango.Style.NORMAL)
            cell.set_property("foreground-set", bool(model.iter_parent(it)))
            cell.set_property("foreground", "#aaaaaa")

        app_col.set_cell_data_func(name_rend, _name_cell_data)
        app_col.set_sort_column_id(_SC_NAME)
        app_col.set_resizable(True)
        app_col.set_expand(True)
        app_col.set_min_width(150)
        self.store_tree.set_expander_column(app_col)
        self.store_tree.append_column(app_col)

        desc_renderer = Gtk.CellRendererText()
        desc_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        desc_col = Gtk.TreeViewColumn()
        self.store_tree_col_description = desc_col
        desc_col.pack_start(desc_renderer, True)
        desc_col.add_attribute(desc_renderer, "text", _SC_DESCRIPTION)
        desc_col.set_resizable(True)
        desc_col.set_expand(True)
        desc_col.set_min_width(150)
        self.store_tree.append_column(desc_col)

        source_renderer = Gtk.CellRendererText()
        source_col = Gtk.TreeViewColumn()
        self.store_tree_col_source = source_col
        source_col.pack_start(source_renderer, True)
        source_col.add_attribute(source_renderer, "text", _SC_SOURCE)
        source_col.set_sort_column_id(_SC_SOURCE)
        source_col.set_resizable(True)
        source_col.set_fixed_width(90)
        self.store_tree.append_column(source_col)

        version_renderer = Gtk.CellRendererText()
        version_col = Gtk.TreeViewColumn()
        self.store_tree_col_version = version_col
        version_col.pack_start(version_renderer, True)
        version_col.add_attribute(version_renderer, "text", _SC_VERSION)
        version_col.set_sort_column_id(_SC_VERSION)
        version_col.set_resizable(True)
        version_col.set_fixed_width(80)
        self.store_tree.append_column(version_col)

        size_renderer = Gtk.CellRendererText()
        size_col = Gtk.TreeViewColumn()
        self.store_tree_col_size = size_col
        size_col.pack_start(size_renderer, True)
        size_col.add_attribute(size_renderer, "text", _SC_SIZE)
        size_col.set_resizable(True)
        size_col.set_fixed_width(100)
        self.store_tree.append_column(size_col)

        store_scroller = Gtk.ScrolledWindow()
        store_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        store_scroller.add(self.store_tree)
        container.pack_start(store_scroller, True, True, 0)

        # Action bar
        store_action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        store_action_bar.get_style_context().add_class("action-bar")
        container.pack_start(store_action_bar, False, False, 0)

        self.store_install_btn = Gtk.Button()
        self.store_install_btn.get_style_context().add_class("suggested-action")
        self.store_install_btn.connect("clicked", self.on_store_install)
        self.store_install_btn.set_sensitive(False)
        store_action_bar.pack_start(self.store_install_btn, False, False, 0)

        self.store_status = Gtk.Label()
        self.store_status.set_xalign(0)
        self.store_status.set_line_wrap(True)
        store_action_bar.pack_start(self.store_status, True, True, 0)

    def _build_packages_page(self, container: Gtk.Box) -> None:
        self.packages_title_label = Gtk.Label()
        self.packages_title_label.set_xalign(0)
        container.pack_start(self.packages_title_label, False, False, 0)

        self.packages_subtitle_label = Gtk.Label()
        self.packages_subtitle_label.set_xalign(0)
        self.packages_subtitle_label.set_line_wrap(True)
        self.packages_subtitle_label.get_style_context().add_class("dim-label")
        container.pack_start(self.packages_subtitle_label, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.pack_start(toolbar, False, False, 0)

        self.packages_search_entry = Gtk.SearchEntry()
        self.packages_search_entry.set_hexpand(True)
        self.packages_search_entry.connect("search-changed", self._on_packages_search_changed)
        toolbar.pack_start(self.packages_search_entry, True, True, 0)

        self.packages_filter_all_btn = Gtk.ToggleButton()
        self.packages_filter_all_btn.get_style_context().add_class("filter-chip")
        self.packages_filter_all_btn.set_active(True)
        self.packages_filter_all_btn.connect("toggled", self._on_packages_filter_all_toggled)
        toolbar.pack_start(self.packages_filter_all_btn, False, False, 0)

        self.packages_filter_upgradable_btn = Gtk.ToggleButton()
        self.packages_filter_upgradable_btn.get_style_context().add_class("filter-chip")
        self.packages_filter_upgradable_btn.connect("toggled", self._on_packages_filter_upgradable_toggled)
        toolbar.pack_start(self.packages_filter_upgradable_btn, False, False, 0)

        self.packages_refresh_btn = Gtk.Button()
        self.packages_refresh_btn.connect("clicked", self._on_packages_refresh)
        toolbar.pack_start(self.packages_refresh_btn, False, False, 0)

        self.packages_summary_label = Gtk.Label()
        self.packages_summary_label.set_xalign(0)
        self.packages_summary_label.get_style_context().add_class("dim-label")
        container.pack_start(self.packages_summary_label, False, False, 0)

        self.packages_store = Gtk.ListStore(
            str,   # name
            str,   # version
            str,   # new_version
            int,   # size_kib
            str,   # size_str
            str,   # description
            bool,  # upgradable
            GObject.TYPE_PYOBJECT,  # PackageInfo
        )
        self.packages_tree = Gtk.TreeView(model=self.packages_store)
        self.packages_tree.set_headers_visible(True)
        self.packages_tree.set_enable_search(False)
        self.packages_tree.set_rubber_banding(True)
        self.packages_tree.connect("button-press-event", self.on_packages_tree_button_press)

        pkg_selection = self.packages_tree.get_selection()
        pkg_selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        pkg_selection.connect("changed", self._on_package_selection_changed)

        name_renderer = Gtk.CellRendererText()
        name_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_name = Gtk.TreeViewColumn()
        self.packages_tree_col_name.pack_start(name_renderer, True)
        self.packages_tree_col_name.add_attribute(name_renderer, "text", _PC_NAME)
        self.packages_tree_col_name.set_sort_column_id(_PC_NAME)
        self.packages_tree_col_name.set_resizable(True)
        self.packages_tree_col_name.set_expand(True)
        self.packages_tree_col_name.set_min_width(160)
        self.packages_tree.append_column(self.packages_tree_col_name)

        version_renderer = Gtk.CellRendererText()
        version_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_version = Gtk.TreeViewColumn()
        self.packages_tree_col_version.pack_start(version_renderer, True)
        self.packages_tree_col_version.add_attribute(version_renderer, "text", _PC_VERSION)
        self.packages_tree_col_version.set_sort_column_id(_PC_VERSION)
        self.packages_tree_col_version.set_resizable(True)
        self.packages_tree_col_version.set_fixed_width(140)
        self.packages_tree.append_column(self.packages_tree_col_version)

        new_version_renderer = Gtk.CellRendererText()
        new_version_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_new_version = Gtk.TreeViewColumn()
        self.packages_tree_col_new_version.pack_start(new_version_renderer, True)
        self.packages_tree_col_new_version.add_attribute(new_version_renderer, "text", _PC_NEW_VERSION)
        self.packages_tree_col_new_version.set_sort_column_id(_PC_NEW_VERSION)
        self.packages_tree_col_new_version.set_resizable(True)
        self.packages_tree_col_new_version.set_fixed_width(140)
        self.packages_tree.append_column(self.packages_tree_col_new_version)

        size_renderer = Gtk.CellRendererText()
        self.packages_tree_col_size = Gtk.TreeViewColumn()
        self.packages_tree_col_size.pack_start(size_renderer, True)
        self.packages_tree_col_size.add_attribute(size_renderer, "text", _PC_SIZE_STR)
        self.packages_tree_col_size.set_sort_column_id(_PC_SIZE_KIB)
        self.packages_tree_col_size.set_resizable(True)
        self.packages_tree_col_size.set_fixed_width(90)
        self.packages_tree.append_column(self.packages_tree_col_size)

        desc_renderer = Gtk.CellRendererText()
        desc_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.packages_tree_col_description = Gtk.TreeViewColumn()
        self.packages_tree_col_description.pack_start(desc_renderer, True)
        self.packages_tree_col_description.add_attribute(desc_renderer, "text", _PC_DESCRIPTION)
        self.packages_tree_col_description.set_resizable(True)
        self.packages_tree_col_description.set_expand(True)
        self.packages_tree_col_description.set_min_width(200)
        self.packages_tree.append_column(self.packages_tree_col_description)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.packages_tree)
        container.pack_start(scroller, True, True, 0)

        action_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        action_bar.get_style_context().add_class("action-bar")
        container.pack_start(action_bar, False, False, 0)

        package_button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        package_button_row.set_halign(Gtk.Align.START)
        action_bar.pack_start(package_button_row, False, False, 0)

        self.packages_update_btn = Gtk.Button()
        self.packages_update_btn.get_style_context().add_class("compact-action")
        self.packages_update_btn.get_style_context().add_class("suggested-action")
        self.packages_update_btn.set_sensitive(False)
        self.packages_update_btn.connect("clicked", self._on_update_selected_packages)
        package_button_row.pack_start(self.packages_update_btn, False, False, 0)

        self.packages_update_all_btn = Gtk.Button()
        self.packages_update_all_btn.get_style_context().add_class("compact-action")
        self.packages_update_all_btn.get_style_context().add_class("suggested-action")
        self.packages_update_all_btn.set_sensitive(False)
        self.packages_update_all_btn.connect("clicked", self._on_update_all_packages)
        package_button_row.pack_start(self.packages_update_all_btn, False, False, 0)

        self.packages_changelog_btn = Gtk.Button()
        self.packages_changelog_btn.get_style_context().add_class("compact-action")
        self.packages_changelog_btn.set_sensitive(False)
        self.packages_changelog_btn.connect("clicked", self._on_package_changelog)
        package_button_row.pack_start(self.packages_changelog_btn, False, False, 0)

        self.packages_export_selected_btn = Gtk.Button()
        self.packages_export_selected_btn.get_style_context().add_class("compact-action")
        self.packages_export_selected_btn.set_sensitive(False)
        self.packages_export_selected_btn.connect("clicked", self._on_export_selected_packages)
        package_button_row.pack_start(self.packages_export_selected_btn, False, False, 0)

        self.packages_status = Gtk.Label()
        self.packages_status.set_xalign(0)
        self.packages_status.set_line_wrap(True)
        self.packages_status.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.packages_status.set_lines(2)
        self.packages_status.set_ellipsize(Pango.EllipsizeMode.END)
        action_bar.pack_start(self.packages_status, False, False, 0)

    def _build_operations_page(self, container: Gtk.Box) -> None:
        title = Gtk.Label()
        title.set_markup('<span size="large" weight="bold">Devam Eden İşlemler</span>')
        title.set_xalign(0)
        container.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="APT/DPKG kilidini tutan veya paket işlemi çalıştıran süreçler.")
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        subtitle.get_style_context().add_class("dim-label")
        container.pack_start(subtitle, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        container.pack_start(toolbar, False, False, 0)

        self.operations_refresh_btn = Gtk.Button(label="Yenile")
        self.operations_refresh_btn.connect("clicked", self._on_operations_refresh)
        toolbar.pack_start(self.operations_refresh_btn, False, False, 0)

        self.operations_status = Gtk.Label()
        self.operations_status.set_xalign(0)
        self.operations_status.get_style_context().add_class("dim-label")
        toolbar.pack_start(self.operations_status, True, True, 0)

        self.operations_pause_btn = Gtk.Button(label="Duraklat")
        self.operations_pause_btn.set_sensitive(False)
        self.operations_pause_btn.connect("clicked", self._on_operations_pause)
        toolbar.pack_end(self.operations_pause_btn, False, False, 0)

        self.operations_cancel_btn = Gtk.Button(label="İptal Et")
        self.operations_cancel_btn.get_style_context().add_class("destructive-action")
        self.operations_cancel_btn.set_sensitive(False)
        self.operations_cancel_btn.connect("clicked", self._on_operations_cancel)
        toolbar.pack_end(self.operations_cancel_btn, False, False, 0)

        self.operations_store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str)
        self.operations_tree = Gtk.TreeView(model=self.operations_store)
        self.operations_tree.set_headers_visible(True)
        self.operations_tree.set_enable_search(False)
        self.operations_tree.get_selection().connect("changed", self._on_operations_selection_changed)

        icon_renderer = Gtk.CellRendererPixbuf()
        icon_col = Gtk.TreeViewColumn("", icon_renderer, pixbuf=_OC_ICON)
        icon_col.set_fixed_width(36)
        self.operations_tree.append_column(icon_col)

        pid_renderer = Gtk.CellRendererText()
        pid_col = Gtk.TreeViewColumn("PID", pid_renderer, text=_OC_PID)
        pid_col.set_fixed_width(80)
        self.operations_tree.append_column(pid_col)

        command_renderer = Gtk.CellRendererText()
        command_renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        command_col = Gtk.TreeViewColumn("İşlem", command_renderer, text=_OC_COMMAND)
        command_col.set_expand(True)
        command_col.set_min_width(260)
        self.operations_tree.append_column(command_col)

        packages_renderer = Gtk.CellRendererText()
        packages_renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        packages_col = Gtk.TreeViewColumn("Paket / Durum", packages_renderer, text=_OC_PACKAGES)
        packages_col.set_expand(True)
        packages_col.set_min_width(220)
        self.operations_tree.append_column(packages_col)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.operations_tree)
        container.pack_start(scroller, True, True, 0)

    # ── Installed apps handlers ────────────────────────────────────────────

    def _on_notebook_switch_page(self, _notebook: Gtk.Notebook, _page, page_num: int) -> None:
        # Page 2 = Packages tab; lazy-load on first visit
        if page_num == 2 and not self.packages and not self.packages_loading:
            self.reload_packages_async()
        if page_num == 3:
            self._refresh_operations_list()

    def on_applications_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.application_search_text = entry.get_text()
        self._render_applications_list()

    def on_application_filter_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if getattr(self, "_updating_application_filters", False):
            return
        if not button.get_active():
            if source == self.application_filter_source:
                button.set_active(True)
            return
        self._updating_application_filters = True
        for filter_source, filter_button in self.application_filter_buttons.items():
            filter_button.set_active(filter_source == source)
        self._updating_application_filters = False
        self.application_filter_source = source
        self._render_applications_list()

    def on_reload_applications(self, *_args) -> None:
        self.reload_applications_async()

    def on_flatpak_cleanup(self, *_args) -> None:
        lang = self.preferences.language
        self._run_application_task(
            self.application_registry.flatpak_cleanup,
            "applications_flatpak_cleanup_done",
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_flatpak_cleanup"),
            progress_message="",
        )

    def on_check_for_updates(self, *_args) -> None:
        lang = self.preferences.language
        self._run_application_task(
            self.application_registry.refresh_update_cache,
            "applications_updates_checked",
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_progress_check"),
            progress_message="",
        )

    def on_update_all_applications(self, _button: Gtk.Button) -> None:
        if not self.applications:
            self._set_applications_status(t(self.preferences.language, "applications_empty"), "#cc7a00")
            return
        lang = self.preferences.language
        self._run_application_task(
            lambda: self.application_registry.update_all(self.applications),
            "applications_update_done",
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_progress_update_all"),
            progress_message="",
        )

    def on_application_tree_activated(self, _tree: Gtk.TreeView, path, _col) -> None:
        it = self.applications_store.get_iter(path)
        if it is None:
            return
        application = self.applications_store.get_value(it, _AC_APP)
        if application is not None:
            self.on_launch_application(None, application)

    def on_application_tree_button_press(self, _tree: Gtk.TreeView, event) -> bool:
        if event.button != 3:
            return False
        result = self.applications_tree.get_path_at_pos(int(event.x), int(event.y))
        if result is None:
            return False
        path, _col, _cx, _cy = result
        selection = self.applications_tree.get_selection()
        # Only reset selection if the clicked row is not already selected
        # (preserves multi-selection when right-clicking on one of the selected rows)
        if not selection.path_is_selected(path):
            self.applications_tree.set_cursor(path)
        it = self.applications_store.get_iter(path)
        if it is None:
            return False
        application = self.applications_store.get_value(it, _AC_APP)
        if application is None:
            return False
        self._show_application_context_menu(application, event)
        return True

    def on_application_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        count = len(paths)
        has_sel = count > 0
        application = model.get_value(model.get_iter(paths[0]), _AC_APP) if count == 1 else None
        single = count == 1
        multi = count > 1
        actionable = has_sel and not self.applications_busy and not self.applications_loading
        for btn in (
            self.applications_launch_btn,
            self.applications_action_location_btn,
        ):
            btn.set_sensitive(actionable and single)
        self.applications_action_remove_btn.set_sensitive(actionable and single)
        self.applications_bulk_remove_btn.set_sensitive(actionable and multi)
        update_ok = (
            actionable
            and single
            and application is not None
            and application.update_available
            and (application.source != SOURCE_APPIMAGE or application.update_supported)
        )
        self.applications_action_update_btn.set_sensitive(update_ok)
        is_flatpak = single and application is not None and application.source == SOURCE_FLATPAK
        self.applications_permissions_btn.set_sensitive(is_flatpak and actionable)
        self.applications_rollback_btn.set_sensitive(is_flatpak and actionable)
        is_apt = single and application is not None and application.source == SOURCE_APT
        self.applications_changelog_btn.set_sensitive((is_apt or is_flatpak) and actionable)
        self.applications_export_selected_btn.set_sensitive(has_sel)

    def _on_selected_app_action(self, callback: Callable) -> None:
        selection = self.applications_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        application = model.get_value(model.get_iter(paths[0]), _AC_APP)
        if application is not None:
            callback(None, application)

    def _show_application_context_menu(self, application: UnifiedApplication, event) -> None:
        menu = Gtk.Menu()
        items = [
            (t(self.preferences.language, "applications_launch"), self.on_launch_application, True),
            (t(self.preferences.language, "applications_update"), self.on_update_application,
             application.source != SOURCE_APPIMAGE or application.update_supported),
            (t(self.preferences.language, "applications_open_location"), self.on_open_application_location, True),
            (t(self.preferences.language, "applications_remove"), self.on_remove_application, True),
        ]
        if application.source == SOURCE_FLATPAK:
            items.append((t(self.preferences.language, "flatpak_permissions_btn"), self.on_flatpak_permissions, True))
            items.append((t(self.preferences.language, "flatpak_rollback_menu"), self.on_flatpak_rollback, True))
        if application.source in (SOURCE_APT, SOURCE_FLATPAK):
            items.append((t(self.preferences.language, "changelog_menu"), self.on_show_changelog, True))
        for label, callback, sensitive in items:
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(sensitive)
            item.connect("activate", lambda _item, func=callback: func(None, application))
            menu.append(item)
        menu.show_all()
        if hasattr(menu, "popup_at_pointer"):
            menu.popup_at_pointer(event)
        else:
            menu.popup(None, None, None, None, event.button, event.time)

    def on_launch_application(self, _button, application: UnifiedApplication) -> None:
        self._run_application_task(
            lambda: self.application_registry.launch(application),
            "applications_launch_started",
            refresh_after=False,
        )

    def on_update_application(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        self._run_application_task(
            lambda: self.application_registry.update(application),
            "applications_update_done",
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_progress_update"),
            progress_message=application.name,
        )

    def on_open_application_location(self, _button, application: UnifiedApplication) -> None:
        self._run_application_task(
            lambda: self.application_registry.open_location(application),
            "applications_location_opened",
            refresh_after=False,
        )

    def on_remove_application(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "applications_remove_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        remove_btn = dialog.add_button(t(lang, "applications_remove"), Gtk.ResponseType.OK)
        remove_btn.get_style_context().add_class("destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        msg_label = Gtk.Label(label=t(lang, "applications_remove_message").format(
            name=application.name,
            source=self._application_source_label(application.source),
        ))
        msg_label.set_line_wrap(True)
        msg_label.set_xalign(0)
        content.pack_start(msg_label, False, False, 0)

        purge_check = Gtk.CheckButton(label=t(lang, "applications_purge_confirm"))
        content.pack_start(purge_check, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        purge = purge_check.get_active()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return

        success_key = "applications_purge_done" if purge else "applications_remove_done"
        self._run_application_task(
            lambda: self.application_registry.remove(application, purge=purge),
            success_key,
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_progress_remove"),
            progress_message=application.name,
        )

    def reload_applications_async(self) -> None:
        if self.applications_loading:
            return
        self.applications_loading = True
        self.application_issues = []
        self.application_provider_errors = []
        self._set_applications_status(t(self.preferences.language, "applications_loading"), "#666666")
        self._set_application_controls_sensitive(True)
        threading.Thread(target=self._load_applications_worker, daemon=True).start()

    def _load_applications_worker(self) -> None:
        try:
            snapshot = self.application_registry.load()
        except Exception as exc:
            snapshot = ApplicationSnapshot(applications=[], provider_errors=[str(exc)])
        GLib.idle_add(self._finish_applications_load, snapshot)

    def _finish_applications_load(self, snapshot: ApplicationSnapshot) -> bool:
        self.applications_loading = False
        self.applications = snapshot.applications
        self.application_issues = snapshot.issues
        self.application_provider_errors = snapshot.provider_errors
        # Update installed IDs for store "already installed" detection
        self.installed_package_ids = {
            app.package_name for app in self.applications
            if app.source in (SOURCE_FLATPAK, SOURCE_SNAP)
        }
        self._render_applications_list()
        if hasattr(self, "store_tree"):
            self.on_store_result_selected(self.store_tree.get_selection())
        if self.application_provider_errors and not self.applications:
            self._set_applications_status(t(self.preferences.language, "applications_load_partial"), "#cc7a00")
        else:
            self._set_applications_status(t(self.preferences.language, "applications_loaded"), "#1f7a1f")
        if not hasattr(self, "_startup_update_done"):
            self._startup_update_done = True
            def _silent_check():
                self.application_registry.refresh_update_cache_silent()
                GLib.idle_add(self.reload_applications_async)
            threading.Thread(target=_silent_check, daemon=True).start()
        return False

    def _run_application_task(
        self,
        task: Callable[[], None],
        success_key: str,
        refresh_after: bool,
        retry: bool = False,
        show_progress: bool = False,
        progress_title: str = "",
        progress_message: str = "",
    ) -> None:
        if self.applications_busy and not retry:
            return
        self.applications_busy = True
        self._set_application_controls_sensitive(False)
        self._set_applications_status(t(self.preferences.language, "applications_action_running"), "#666666")

        progress_dialog: OperationProgressWindow | None = None
        op_key: str | None = None
        if show_progress:
            self._active_op_seq += 1
            op_key = f"app_{self._active_op_seq}"
            self._register_active_op(
                op_key, progress_title, progress_message or progress_title, None,
                cancel_fn=self.application_registry.runner.cancel_current,
            )
            progress_dialog = OperationProgressWindow(
                title=progress_title,
                message=progress_message,
                parent=self,
                on_progress=lambda f, lbl, k=op_key: self._update_op_row(k, f, lbl),
            )
            self.application_registry.runner.set_output_callback(
                lambda line: GLib.idle_add(progress_dialog.append_log, line)
            )

        def worker() -> None:
            try:
                task()
            except AuthRequiredError as exc:
                self.application_registry.runner.set_output_callback(None)
                if op_key:
                    GLib.idle_add(self._unregister_active_op, op_key)
                if progress_dialog is not None:
                    GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(
                    self._handle_application_auth_required,
                    task, success_key, refresh_after, exc, retry,
                    show_progress, progress_title, progress_message,
                )
            except BackendError as exc:
                self.application_registry.runner.set_output_callback(None)
                msg = self._application_error_message(str(exc))
                if op_key:
                    GLib.idle_add(self._unregister_active_op, op_key)
                if progress_dialog is not None:
                    GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, False)
            except Exception as exc:
                self.application_registry.runner.set_output_callback(None)
                msg = str(exc)
                if op_key:
                    GLib.idle_add(self._unregister_active_op, op_key)
                if progress_dialog is not None:
                    GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_application_task, False, msg, False)
            else:
                self.application_registry.runner.set_output_callback(None)
                msg = t(self.preferences.language, success_key)
                if op_key:
                    GLib.idle_add(self._unregister_active_op, op_key)
                if progress_dialog is not None:
                    GLib.idle_add(progress_dialog.finish, True, msg)
                GLib.idle_add(self._finish_application_task, True, msg, refresh_after)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_application_auth_required(
        self,
        task: Callable[[], None],
        success_key: str,
        refresh_after: bool,
        exc: AuthRequiredError,
        retry: bool,
        show_progress: bool = False,
        progress_title: str = "",
        progress_message: str = "",
    ) -> bool:
        password = self._ask_sudo_password(
            retry=retry or exc.password_failed,
            message_key="applications_password_message",
            retry_key="applications_password_retry",
        )
        if password is None:
            self._finish_application_task(False, t(self.preferences.language, "status_cancelled"), False)
            return False
        self.application_registry.set_sudo_password(password)
        self.applications_busy = False
        self._run_application_task(
            task, success_key, refresh_after, retry=True,
            show_progress=show_progress, progress_title=progress_title, progress_message=progress_message,
        )
        return False

    def _finish_application_task(self, success: bool, message: str, refresh_after: bool) -> bool:
        self.applications_busy = False
        self._set_application_controls_sensitive(True)
        self._set_applications_status(message, "#1f7a1f" if success else "red")
        if refresh_after:
            self.reload_applications_async()
        return False

    # ── Store handlers ─────────────────────────────────────────────────────

    def on_store_filter_toggled(self, button: Gtk.ToggleButton, source: str) -> None:
        if getattr(self, "_updating_store_filters", False):
            return
        if not button.get_active():
            if source == self.store_filter_source:
                button.set_active(True)
            return
        self._updating_store_filters = True
        for filter_source, filter_button in self.store_filter_buttons.items():
            filter_button.set_active(filter_source == source)
        self._updating_store_filters = False
        self.store_filter_source = source
        # Re-search if there's a current query
        if self.store_results or self.store_search_entry.get_text().strip():
            self.on_store_search(None)

    def on_store_search(self, *_args) -> None:
        query = self.store_search_entry.get_text().strip()
        if not query:
            return
        if self.store_busy:
            return
        self.store_busy = True
        self.store_install_btn.set_sensitive(False)
        self._set_store_status(t(self.preferences.language, "store_searching"), "#666666")
        self.store_results_store.clear()

        sources: set[str] | None = None
        if self.store_filter_source == STORE_FLATPAK:
            sources = {STORE_FLATPAK}
        elif self.store_filter_source == STORE_SNAP:
            sources = {STORE_SNAP}
        elif self.store_filter_source == STORE_APT:
            sources = {STORE_APT}

        def worker() -> None:
            try:
                results = self.store_registry.search(query, sources)
            except BackendError as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc))
            except Exception as exc:
                GLib.idle_add(self._finish_store_search, [], str(exc))
            else:
                GLib.idle_add(self._finish_store_search, results, "")

        threading.Thread(target=worker, daemon=True).start()

    def _finish_store_search(self, results: list[StoreResult], error: str) -> bool:
        self.store_busy = False
        self.store_results = results
        self._render_store_results(results)
        if error:
            self._set_store_status(error, "red")
        elif not results:
            self._set_store_status(t(self.preferences.language, "store_no_results"), "#cc7a00")
        else:
            self._set_store_status(t(self.preferences.language, "store_hint_doubleclick"), "#666666")
        return False

    def on_store_result_selected(self, selection: Gtk.TreeSelection) -> None:
        model, it = selection.get_selected()
        if it is None:
            self.store_install_btn.set_label(t(self.preferences.language, "store_install_btn"))
            self.store_install_btn.set_sensitive(False)
            self.store_install_btn.get_style_context().add_class("suggested-action")
            return
        result: StoreResult = model.get_value(it, _SC_RESULT)
        is_installed = self._store_result_is_installed(result)
        if is_installed:
            self.store_install_btn.set_label(t(self.preferences.language, "store_installed_badge"))
            self.store_install_btn.set_sensitive(False)
            self.store_install_btn.get_style_context().remove_class("suggested-action")
        else:
            self.store_install_btn.set_label(t(self.preferences.language, "store_install_btn"))
            self.store_install_btn.set_sensitive(not self.store_busy)
            self.store_install_btn.get_style_context().add_class("suggested-action")

    def on_store_row_activated(self, tree: Gtk.TreeView, path, _col) -> None:
        it = self.store_results_store.get_iter(path)
        if it is None:
            return
        # If this row has children, double-click toggles expansion; still open detail
        if self.store_results_store.iter_has_child(it):
            if tree.row_expanded(path):
                tree.collapse_row(path)
            else:
                tree.expand_row(path, False)
        result: StoreResult = self.store_results_store.get_value(it, _SC_RESULT)
        if result is not None:
            self._open_store_detail_dialog(result)

    def _open_store_detail_dialog(self, result: StoreResult) -> None:
        AppDetailDialog(
            primary_result=result,
            all_results=self.store_results,
            installed_package_ids=self.installed_package_ids,
            install_callback=self._run_store_install,
            language=self.preferences.language,
            parent=self,
        )

    def on_store_install(self, _button: Gtk.Button) -> None:
        if self.store_busy:
            return
        selection = self.store_tree.get_selection()
        model, it = selection.get_selected()
        if it is None:
            return
        result: StoreResult = model.get_value(it, _SC_RESULT)
        self._open_store_detail_dialog(result)

    def _run_store_install(self, result: StoreResult, retry: bool = False, classic: bool = False) -> None:
        self.store_busy = True
        self.store_install_btn.set_sensitive(False)
        self._set_store_status(t(self.preferences.language, "store_action_running"), "#666666")

        lang = self.preferences.language
        self._active_op_seq += 1
        op_key = f"store_{self._active_op_seq}"
        remote = getattr(result, "remote", None) or "flathub"
        classic_flag = "--classic " if classic else ""
        op_cmd = f"{result.source} install {classic_flag}{remote} {result.app_id}"
        self._register_active_op(
            op_key, op_cmd, result.name, self._get_store_pixbuf(result),
            download_size=result.download_size_str or "",
            cancel_fn=self.store_registry.cancel_current,
        )

        progress_dialog = OperationProgressWindow(
            title=t(lang, "store_install_progress_title"),
            message=result.name,
            parent=self,
            on_progress=lambda f, lbl: self._update_op_row(op_key, f, lbl),
        )
        self.store_registry.set_output_callback(
            lambda line: GLib.idle_add(progress_dialog.append_log, line)
        )

        apt_msg_key = "store_apt_password_message"
        apt_retry_key = "store_apt_password_retry"

        def worker() -> None:
            try:
                self.store_registry.install(result, classic=classic)
            except SnapClassicRequiredError:
                self.store_registry.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                GLib.idle_add(self._handle_snap_classic_required, result)
            except AuthRequiredError as exc:
                self.store_registry.set_output_callback(None)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.destroy)
                msg_key = apt_msg_key if result.source == STORE_APT else "store_password_message"
                retry_key = apt_retry_key if result.source == STORE_APT else "store_password_retry"
                GLib.idle_add(self._handle_store_auth_required, result, exc, retry, msg_key, retry_key, classic)
            except BackendError as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            except Exception as exc:
                self.store_registry.set_output_callback(None)
                msg = str(exc)
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, False, msg)
                GLib.idle_add(self._finish_store_install, False, msg)
            else:
                self.store_registry.set_output_callback(None)
                msg = t(self.preferences.language, "store_install_done")
                GLib.idle_add(self._unregister_active_op, op_key)
                GLib.idle_add(progress_dialog.finish, True, msg)
                GLib.idle_add(self._finish_store_install, True, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_snap_classic_required(self, result: StoreResult) -> bool:
        lang = self.preferences.language
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=t(lang, "store_snap_classic_title"),
        )
        dialog.format_secondary_text(
            t(lang, "store_snap_classic_message", name=result.name)
        )
        dialog.add_button(t(lang, "store_snap_classic_cancel"), Gtk.ResponseType.CANCEL)
        confirm_btn = dialog.add_button(t(lang, "store_snap_classic_confirm"), Gtk.ResponseType.OK)
        confirm_btn.get_style_context().add_class("suggested-action")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            self.store_busy = False
            self._run_store_install(result, retry=True, classic=True)
        else:
            self._finish_store_install(False, t(lang, "status_cancelled"))
        return False

    def _handle_store_auth_required(
        self, result: StoreResult, exc: AuthRequiredError, retry: bool,
        message_key: str = "store_password_message",
        retry_key: str = "store_password_retry",
        classic: bool = False,
    ) -> bool:
        password = self._ask_sudo_password(
            retry=retry or exc.password_failed,
            message_key=message_key,
            retry_key=retry_key,
        )
        if password is None:
            self._finish_store_install(False, t(self.preferences.language, "status_cancelled"))
            return False
        self.store_registry.set_sudo_password(password)
        self.store_busy = False
        self._run_store_install(result, retry=True, classic=classic)
        return False

    def _finish_store_install(self, success: bool, message: str) -> bool:
        self.store_busy = False
        self._set_store_status(message, "#1f7a1f" if success else "red")
        if success:
            self.reload_applications_async()
        else:
            self.on_store_result_selected(self.store_tree.get_selection())
        return False

    # ── Rendering helpers ──────────────────────────────────────────────────

    def _render_applications_list(self) -> None:
        if not hasattr(self, "applications_store"):
            return
        self._update_category_combo()
        self.applications_store.clear()
        items = self._filtered_application_items()
        self.filtered_applications = items

        for application in items:
            pixbuf = self._get_app_pixbuf(application)
            size_str = self._format_application_size(application.installed_size_kib) or ""
            location = application.install_path or application.desktop_file or application.executable
            source_label = self._application_source_label(application.source)
            if application.update_available:
                source_label += " ↑"
            self.applications_store.append([
                pixbuf,
                application.name,
                source_label,
                application.version,
                application.installed_size_kib or 0,
                size_str,
                application.last_updated,
                location,
                application,
            ])

        total = len(self.applications)
        shown = len(items)
        if not items:
            if self.applications:
                self.applications_summary_label.set_text(t(self.preferences.language, "applications_no_results"))
            else:
                self.applications_summary_label.set_text(t(self.preferences.language, "applications_empty"))
        else:
            self.applications_summary_label.set_text(
                t(self.preferences.language, "applications_count_summary").format(count=shown, total=total)
            )
        self._render_application_diagnostics()
        self._set_application_controls_sensitive(not self.applications_busy)
        self.on_application_selection_changed(self.applications_tree.get_selection())

    def _store_result_is_installed(self, result: StoreResult) -> bool:
        if result.app_id in self.installed_package_ids:
            return True
        name_lower = result.name.lower()
        return any(
            r.name.lower() == name_lower and r.app_id in self.installed_package_ids
            for r in self.store_results
        )

    @staticmethod
    def _group_store_results(
        results: list[StoreResult],
    ) -> list[tuple[StoreResult, list[StoreResult]]]:
        """Group results into (parent, [children]) pairs.

        A result is a child when its app_id starts with
        ``parent.app_id + "."`` or ``parent.app_id + "-"``,
        or when its name starts with ``parent.name + " "`` (same source).
        """
        seen: set[str] = set()
        deduped: list[StoreResult] = []
        for r in results:
            key = r.name.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        parent_of: dict[int, int] = {}
        for i, r in enumerate(deduped):
            best_j: int | None = None
            best_score = 0
            for j, cand in enumerate(deduped):
                if i == j:
                    continue
                score = 0
                if r.app_id and cand.app_id:
                    if r.app_id.startswith(cand.app_id + "."):
                        score = len(cand.app_id) + 2
                    elif r.app_id.startswith(cand.app_id + "-"):
                        score = len(cand.app_id) + 1
                if r.source == cand.source:
                    cname = cand.name.lower()
                    if r.name.lower().startswith(cname + " "):
                        score = max(score, len(cname) + 1)
                if score > best_score:
                    best_score = score
                    best_j = j
            if best_j is not None and best_j not in parent_of:
                parent_of[i] = best_j

        children_of: dict[int, list[int]] = {}
        for ci, pi in parent_of.items():
            children_of.setdefault(pi, []).append(ci)

        output: list[tuple[StoreResult, list[StoreResult]]] = []
        for i, r in enumerate(deduped):
            if i in parent_of:
                continue
            kids = [deduped[j] for j in children_of.get(i, [])]
            output.append((r, kids))
        return output

    def _render_store_results(self, results: list[StoreResult]) -> None:
        self.store_results_store.clear()
        groups = self._group_store_results(results)
        for parent, children in groups:
            src = parent.source.capitalize()
            if self._store_result_is_installed(parent):
                src += " ✓"
            parent_it = self.store_results_store.append(None, [
                self._get_store_pixbuf(parent),
                parent.name,
                src,
                parent.description,
                parent.version,
                parent.remote,
                parent.download_size_str,
                parent,
            ])
            for child in children:
                csrc = child.source.capitalize()
                if self._store_result_is_installed(child):
                    csrc += " ✓"
                self.store_results_store.append(parent_it, [
                    self._get_store_pixbuf(child),
                    child.name,
                    csrc,
                    child.description,
                    child.version,
                    child.remote,
                    child.download_size_str,
                    child,
                ])
            if children:
                path = self.store_results_store.get_path(parent_it)
                self.store_tree.expand_row(path, False)

    def _get_store_pixbuf(self, result: StoreResult) -> GdkPixbuf.Pixbuf | None:
        size = 32
        if result.icon_path and os.path.exists(result.icon_path):
            try:
                raw = GdkPixbuf.Pixbuf.new_from_file(result.icon_path)
                return raw.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            except Exception:
                pass
        theme = Gtk.IconTheme.get_default()
        candidates = [result.app_id]
        # Try last component (e.g. org.videolan.VLC -> VLC -> vlc)
        parts = result.app_id.rsplit(".", 1)
        if len(parts) > 1:
            candidates.append(parts[-1].lower())
        candidates.append("application-x-executable")
        for icon_name in candidates:
            try:
                return theme.load_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                pass
        return None

    def _get_app_pixbuf(self, application: UnifiedApplication) -> GdkPixbuf.Pixbuf | None:
        cache_key = application.icon or ""
        if cache_key in self._icon_pixbuf_cache:
            return self._icon_pixbuf_cache[cache_key]
        size = 32
        pixbuf = None
        if application.icon and os.path.exists(application.icon):
            try:
                raw = GdkPixbuf.Pixbuf.new_from_file(application.icon)
                pixbuf = raw.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
            except Exception:
                pass
        if pixbuf is None:
            theme = Gtk.IconTheme.get_default()
            for icon_name in (application.icon or "", "application-x-executable"):
                if not icon_name:
                    continue
                try:
                    pixbuf = theme.load_icon(icon_name, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    break
                except Exception:
                    pass
        self._icon_pixbuf_cache[cache_key] = pixbuf
        return pixbuf

    def _render_application_diagnostics(self) -> None:
        for row in self.applications_diagnostics_list.get_children():
            self.applications_diagnostics_list.remove(row)
        issue_count = len(self.application_issues)
        provider_count = len(self.application_provider_errors)
        self.applications_diagnostics_label.set_text(
            t(self.preferences.language, "applications_diagnostics_summary").format(
                issues=issue_count, providers=provider_count,
            )
        )
        for issue in self.application_issues[:8]:
            row = Gtk.ListBoxRow()
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_line_wrap(True)
            detail = f"{issue.title}: {issue.detail}" if issue.detail else issue.title
            label.set_text(detail)
            row.add(label)
            self.applications_diagnostics_list.add(row)
        for error in self.application_provider_errors[:4]:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=error)
            label.set_xalign(0)
            label.set_line_wrap(True)
            row.add(label)
            self.applications_diagnostics_list.add(row)
        self.applications_diagnostics_list.show_all()

    def _filtered_application_items(self) -> list[UnifiedApplication]:
        query = self.application_search_text.strip().lower()
        selected_source = self.application_filter_source
        selected_category = getattr(self, "application_filter_category", "__all__")
        items = []
        for application in self.applications:
            haystack = " ".join((
                application.name, application.category,
                application.source, application.version,
            )).lower()
            if query and query not in haystack:
                continue
            if selected_source == "updates":
                if not application.update_available:
                    continue
            elif selected_source != "all" and application.source != selected_source:
                continue
            if selected_category != "__all__" and application.category != selected_category:
                continue
            items.append(application)
        items.sort(key=lambda item: item.name.lower())
        return items

    # ── Shared helpers ─────────────────────────────────────────────────────

    def _ask_sudo_password(
        self,
        retry: bool,
        message_key: str = "applications_password_message",
        retry_key: str = "applications_password_retry",
    ) -> str | None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "password_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(self.preferences.language, "password_continue"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        message = t(self.preferences.language, retry_key if retry else message_key)
        label = Gtk.Label(label=message)
        label.set_line_wrap(True)
        label.set_xalign(0)
        content.pack_start(label, False, False, 0)

        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_activates_default(True)
        entry.set_placeholder_text(t(self.preferences.language, "password_placeholder"))
        content.pack_start(entry, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        password = entry.get_text()
        dialog.destroy()
        return password if response == Gtk.ResponseType.OK else None

    def _set_application_controls_sensitive(self, enabled: bool) -> None:
        sensitive = enabled and not self.applications_loading
        for widget in (
            self.applications_refresh_btn,
            self.applications_check_updates_btn,
            self.applications_update_all_btn,
        ):
            widget.set_sensitive(sensitive)
        self.applications_update_all_btn.set_sensitive(sensitive and bool(self.applications))
        if hasattr(self, "applications_tree"):
            self.on_application_selection_changed(self.applications_tree.get_selection())
    def _set_applications_status(self, message: str, color: str) -> None:
        safe_message = GLib.markup_escape_text(message)
        self.applications_status.set_markup(f'<span foreground="{color}">{safe_message}</span>')

    def _set_store_status(self, message: str, color: str) -> None:
        if not message:
            self.store_status.set_text("")
            return
        safe_message = GLib.markup_escape_text(message)
        self.store_status.set_markup(f'<span foreground="{color}">{safe_message}</span>')

    def _application_source_label(self, source: str) -> str:
        return t(self.preferences.language, f"applications_source_{source}")

    def _application_error_message(self, message: str) -> str:
        if message == "Manual update required":
            return t(self.preferences.language, "applications_manual_update_required")
        lowered = message.lower()
        if "dpkg" in lowered and ("configure -a" in message or "kesintiye" in lowered):
            return t(self.preferences.language, "applications_dpkg_interrupted")
        if (
            "/var/lib/apt/lists/lock" in message
            or "lock-frontend" in lowered
            or "kilidi alınamadı" in lowered
            or "önbellek kilidi" in lowered
            or "could not get lock" in lowered
            or "kilitlenemiyor" in lowered
        ):
            return t(self.preferences.language, "applications_apt_locked")
        return translate_backend_message(self.preferences.language, message)

    def _format_application_size(self, kib: int | None) -> str:
        if kib is None:
            return ""
        if kib >= 1024 * 1024:
            return f"{kib / (1024 * 1024):.1f} GB"
        if kib >= 1024:
            return f"{kib / 1024:.1f} MB"
        return f"{kib} KB"

    # ── Theme & texts ──────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        self.css_provider.load_from_data(get_theme_css(self.preferences.theme).encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _refresh_texts(self) -> None:
        lang = self.preferences.language
        self.set_title(APP_TITLE)
        self.settings_btn.set_label(t(lang, "settings"))
        self.installed_tab_label.set_text(t(lang, "tab_installed"))
        self.store_tab_label.set_text(t(lang, "tab_store"))
        self.packages_tab_label.set_text(t(lang, "tab_packages"))

        # Installed page
        self.applications_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "applications_title")}</span>'
        )
        self.applications_subtitle_label.set_text(t(lang, "applications_subtitle"))
        self.applications_search_entry.set_placeholder_text(t(lang, "applications_search_placeholder"))
        self.applications_refresh_btn.set_label(t(lang, "applications_refresh"))
        self.applications_check_updates_btn.set_label(t(lang, "applications_check_updates"))
        self.applications_update_all_btn.set_label(t(lang, "applications_update_all"))
        self.applications_tree_col_app.set_title(t(lang, "applications_col_app"))
        self.applications_tree_col_source.set_title(t(lang, "applications_col_source"))
        self.applications_tree_col_version.set_title(t(lang, "applications_col_version"))
        self.applications_tree_col_size.set_title(t(lang, "applications_col_size"))
        self.applications_tree_col_date.set_title(t(lang, "applications_col_date"))
        self.applications_tree_col_location.set_title(t(lang, "applications_col_location"))
        self.applications_launch_btn.set_label(t(lang, "applications_launch"))
        self.applications_action_update_btn.set_label(t(lang, "applications_update"))
        self.applications_action_location_btn.set_label(t(lang, "applications_open_location"))
        self.applications_action_remove_btn.set_label(t(lang, "applications_remove"))
        self.applications_bulk_remove_btn.set_label(t(lang, "applications_remove") + " (×N)")
        self.applications_permissions_btn.set_label(t(lang, "flatpak_permissions_btn"))
        self.applications_rollback_btn.set_label(t(lang, "flatpak_rollback_menu"))
        self.applications_changelog_btn.set_label(t(lang, "changelog_menu"))
        self.applications_export_btn.set_label(t(lang, "applications_export"))
        self.applications_add_appimage_btn.set_label(t(lang, "appimage_register_btn"))
        self.applications_export_selected_btn.set_label(t(lang, "export_selected"))
        self.applications_category_label.set_text(t(lang, "applications_category_filter") + ": ")
        self.applications_diagnostics_expander.set_label(t(lang, "applications_diagnostics"))
        self.applications_flatpak_cleanup_btn.set_label(t(lang, "applications_flatpak_cleanup"))
        for source, button in self.application_filter_buttons.items():
            button.set_label(self._application_source_label(source))

        # Store page
        self.store_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "store_title")}</span>'
        )
        self.store_subtitle_label.set_text(t(lang, "store_subtitle"))
        self.store_search_entry.set_placeholder_text(t(lang, "store_search_placeholder"))
        self.store_search_btn.set_label(t(lang, "store_search_btn"))
        self.store_tree_col_name.set_title(t(lang, "store_col_name"))
        self.store_tree_col_description.set_title(t(lang, "store_col_description"))
        self.store_tree_col_source.set_title(t(lang, "store_col_source"))
        self.store_tree_col_version.set_title(t(lang, "store_col_version"))
        self.store_tree_col_size.set_title(t(lang, "store_col_size"))
        for source, button in self.store_filter_buttons.items():
            label_key = f"store_source_{source}"
            button.set_label(t(lang, label_key))
        self._set_store_status(t(lang, "store_empty"), "#666666")
        self.on_store_result_selected(self.store_tree.get_selection())
        self._render_applications_list()

        # Packages page
        self.packages_title_label.set_markup(
            f'<span size="large" weight="bold">{t(lang, "packages_title")}</span>'
        )
        self.packages_subtitle_label.set_text(t(lang, "packages_subtitle"))
        self.packages_search_entry.set_placeholder_text(t(lang, "packages_search_placeholder"))
        self.packages_refresh_btn.set_label(t(lang, "packages_refresh"))
        self.packages_filter_all_btn.set_label(t(lang, "packages_filter_all"))
        self.packages_filter_upgradable_btn.set_label(t(lang, "packages_filter_upgradable"))
        self.packages_tree_col_name.set_title(t(lang, "packages_col_name"))
        self.packages_tree_col_version.set_title(t(lang, "packages_col_version"))
        self.packages_tree_col_new_version.set_title(t(lang, "packages_col_new_version"))
        self.packages_tree_col_size.set_title(t(lang, "packages_col_size"))
        self.packages_tree_col_description.set_title(t(lang, "packages_col_description"))
        self.packages_update_btn.set_label(t(lang, "packages_update_selected"))
        self.packages_update_all_btn.set_label(t(lang, "packages_update_all"))
        self.packages_changelog_btn.set_label(t(lang, "packages_changelog"))
        self.packages_export_selected_btn.set_label(t(lang, "export_selected"))

    def on_open_settings(self, _button: Gtk.Button) -> None:
        dialog = Gtk.Dialog(
            title=t(self.preferences.language, "settings_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(t(self.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(self.preferences.language, "settings_save"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        subtitle = Gtk.Label(label=t(self.preferences.language, "settings_subtitle"))
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        content.pack_start(subtitle, False, False, 0)

        form = Gtk.Grid(column_spacing=12, row_spacing=12)
        content.pack_start(form, False, False, 0)

        language_label = Gtk.Label(label=t(self.preferences.language, "language"))
        language_label.set_xalign(0)
        theme_label = Gtk.Label(label=t(self.preferences.language, "theme"))
        theme_label.set_xalign(0)

        language_combo = Gtk.ComboBoxText()
        language_combo.append("tr", t(self.preferences.language, "language_tr"))
        language_combo.append("en", t(self.preferences.language, "language_en"))
        language_combo.set_active_id(self.preferences.language)

        theme_combo = Gtk.ComboBoxText()
        theme_combo.append("dark", t(self.preferences.language, "theme_dark"))
        theme_combo.append("light", t(self.preferences.language, "theme_light"))
        theme_combo.set_active_id(self.preferences.theme)

        form.attach(language_label, 0, 0, 1, 1)
        form.attach(language_combo, 1, 0, 1, 1)
        form.attach(theme_label, 0, 1, 1, 1)
        form.attach(theme_combo, 1, 1, 1, 1)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_lang = language_combo.get_active_id() or self.preferences.language
            new_theme = theme_combo.get_active_id() or self.preferences.theme
            self.preferences = AppPreferences(language=new_lang, theme=new_theme)
            self.preferences_store.save(self.preferences)
            self._apply_theme()
            self._refresh_texts()
        dialog.destroy()

    # ── New feature handlers ───────────────────────────────────────────────

    # -- Packages tab handlers -----------------------------------------------

    def _short_task_error(self, message: str) -> str:
        lowered = message.lower()
        if "lock-frontend" in lowered or "kilidi alınamadı" in lowered or "kilitlenemiyor" in lowered:
            return "APT şu anda başka bir işlem tarafından kullanılıyor. Diğer güncelleme/kurulum bitince tekrar dene."
        if "dpkg" in lowered and "configure -a" in lowered:
            return "DPKG yarım kalmış. Önce bakım işlemi gerekiyor: sudo dpkg --configure -a"
        if "access denied" in lowered or "sudo ile dene" in lowered:
            return "Yönetici izni gerekiyor."
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), message.strip())
        return first_line[:180]

    def reload_packages_async(self) -> None:
        if self.packages_loading:
            return
        self.packages_loading = True
        self.packages_status.set_markup(f'<span color="#666666">{t(self.preferences.language, "packages_loading")}</span>')
        threading.Thread(target=self._load_packages_worker, daemon=True).start()

    def _load_packages_worker(self) -> None:
        try:
            packages = self.application_registry.list_packages()
        except Exception as exc:
            packages = []
            GLib.idle_add(self._finish_packages_load, packages, str(exc))
            return
        GLib.idle_add(self._finish_packages_load, packages, None)

    def _finish_packages_load(self, packages: list[PackageInfo], error: str | None) -> bool:
        self.packages_loading = False
        self.packages = packages
        self._render_packages_list()
        lang = self.preferences.language
        if error:
            self.packages_status.set_markup(f'<span color="#cc0000">{GLib.markup_escape_text(error)}</span>')
        else:
            upgradable_count = sum(1 for p in packages if p.update_available)
            msg = t(lang, "packages_loaded").format(total=len(packages), upgradable=upgradable_count)
            self.packages_status.set_markup(f'<span color="#1f7a1f">{GLib.markup_escape_text(msg)}</span>')
            self.packages_update_all_btn.set_sensitive(upgradable_count > 0)
        return False

    def _render_packages_list(self) -> None:
        self.packages_store.clear()
        # Exclude packages that already appear in the Applications tab (they have a .desktop entry)
        gui_packages = {
            app.package_name
            for app in self.applications
            if app.source == SOURCE_APT and app.package_name
        }
        search = self.packages_search_text.lower()
        for pkg in self.packages:
            if pkg.name in gui_packages:
                continue
            if self.packages_filter_upgradable and not pkg.update_available:
                continue
            if search and search not in pkg.name.lower() and search not in pkg.description.lower():
                continue
            size_kib = pkg.installed_size_kib or 0
            if size_kib >= 1024:
                size_str = f"{size_kib / 1024:.1f} MB"
            elif size_kib > 0:
                size_str = f"{size_kib} KB"
            else:
                size_str = ""
            self.packages_store.append([
                pkg.name,
                pkg.version,
                pkg.new_version if pkg.update_available else "",
                size_kib,
                size_str,
                pkg.description,
                pkg.update_available,
                pkg,
            ])

    def _on_packages_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.packages_search_text = entry.get_text()
        self._render_packages_list()

    def _on_packages_filter_all_toggled(self, button: Gtk.ToggleButton) -> None:
        if getattr(self, "_updating_pkg_filters", False):
            return
        if not button.get_active():
            button.set_active(True)
            return
        self._updating_pkg_filters = True
        self.packages_filter_upgradable_btn.set_active(False)
        self._updating_pkg_filters = False
        self.packages_filter_upgradable = False
        self._render_packages_list()

    def _on_packages_filter_upgradable_toggled(self, button: Gtk.ToggleButton) -> None:
        if getattr(self, "_updating_pkg_filters", False):
            return
        self._updating_pkg_filters = True
        self.packages_filter_all_btn.set_active(not button.get_active())
        self._updating_pkg_filters = False
        self.packages_filter_upgradable = button.get_active()
        self._render_packages_list()

    def _on_packages_refresh(self, *_args) -> None:
        self.reload_packages_async()

    def on_packages_tree_button_press(self, _tree: Gtk.TreeView, event) -> bool:
        if event.button != 3:
            return False
        result = self.packages_tree.get_path_at_pos(int(event.x), int(event.y))
        if result is None:
            return False
        path, _col, _cx, _cy = result
        selection = self.packages_tree.get_selection()
        if not selection.path_is_selected(path):
            self.packages_tree.set_cursor(path)
        it = self.packages_store.get_iter(path)
        if it is None:
            return False
        package: PackageInfo = self.packages_store.get_value(it, _PC_PKG)
        if package is None:
            return False
        self._show_package_context_menu(package, event)
        return True

    def _show_package_context_menu(self, package: PackageInfo, event) -> None:
        selection = self.packages_tree.get_selection()
        model, paths = selection.get_selected_rows()
        selected_packages: list[PackageInfo] = []
        for path in paths:
            it = model.get_iter(path)
            pkg: PackageInfo = model.get_value(it, _PC_PKG)
            if pkg:
                selected_packages.append(pkg)
        selected_upgradable = [pkg for pkg in selected_packages if pkg.update_available]
        single = len(selected_packages) == 1

        menu = Gtk.Menu()
        update_label = t(self.preferences.language, "packages_update_selected")
        if len(selected_upgradable) == 1:
            update_label = f"{selected_upgradable[0].name} güncelle"
        elif len(selected_upgradable) > 1:
            update_label = f"{len(selected_upgradable)} paketi güncelle"
        update_item = Gtk.MenuItem(label=update_label)
        update_item.set_sensitive(bool(selected_upgradable))
        update_item.connect("activate", self._on_update_selected_packages)
        menu.append(update_item)

        changelog_item = Gtk.MenuItem(label=t(self.preferences.language, "packages_changelog"))
        changelog_item.set_sensitive(single)
        changelog_item.connect("activate", self._on_package_changelog)
        menu.append(changelog_item)

        export_item = Gtk.MenuItem(label=t(self.preferences.language, "export_selected"))
        export_item.set_sensitive(bool(selected_packages))
        export_item.connect("activate", self._on_export_selected_packages)
        menu.append(export_item)

        refresh_item = Gtk.MenuItem(label=t(self.preferences.language, "packages_refresh"))
        refresh_item.connect("activate", self._on_packages_refresh)
        menu.append(refresh_item)

        menu.show_all()
        if hasattr(menu, "popup_at_pointer"):
            menu.popup_at_pointer(event)
        else:
            menu.popup(None, None, None, None, event.button, event.time)

    def _register_active_op(
        self,
        key: str,
        command: str,
        summary: str,
        pixbuf: GdkPixbuf.Pixbuf | None,
        download_size: str = "",
        cancel_fn: "Callable[[], None] | None" = None,
    ) -> None:
        initial = f"{summary}  ({download_size})" if download_size else summary
        self._active_ops[key] = {
            "command": command,
            "base_summary": summary,
            "display_summary": initial,
            "pixbuf": pixbuf,
            "row_ref": None,
            "cancel_fn": cancel_fn,
        }
        if self.pages.get_current_page() == 3:
            self._refresh_operations_list()

    def _unregister_active_op(self, key: str) -> None:
        self._active_ops.pop(key, None)
        if hasattr(self, "operations_store") and self.pages.get_current_page() == 3:
            self._refresh_operations_list()

    def _update_op_row(self, key: str, fraction: float, label: str) -> None:
        op = self._active_ops.get(key)
        if not op:
            return
        pct = int(fraction * 100)
        if pct > 0 and pct < 100:
            display = f"{op['base_summary']}  —  {label}  ({pct}%)"
        elif pct >= 100:
            display = f"{op['base_summary']}  —  ✓ Tamamlandı"
        else:
            display = f"{op['base_summary']}  —  {label}" if label and label != "Hazırlanıyor..." else op["base_summary"]
        op["display_summary"] = display
        ref = op.get("row_ref")
        if ref and ref.valid():
            it = self.operations_store.get_iter(ref.get_path())
            self.operations_store.set_value(it, _OC_PACKAGES, display)

    def _on_operations_refresh(self, *_args) -> None:
        self._refresh_operations_list()

    def _refresh_operations_list(self) -> None:
        if not hasattr(self, "operations_store"):
            return
        self.operations_store.clear()
        total_count = 0

        # In-app tracked operations (store installs, app updates)
        for key, op in self._active_ops.items():
            it = self.operations_store.append([
                op["pixbuf"], "●", op["command"], op["display_summary"],
            ])
            path = self.operations_store.get_path(it)
            op["row_ref"] = Gtk.TreeRowReference.new(self.operations_store, path)
            total_count += 1

        # System APT/DPKG processes
        try:
            holders = self.application_registry.runner._apt_lock_holders()
        except Exception:
            holders = []
        for pid, command in holders:
            packages = OperationProgressWindow._packages_from_apt_command(self=None, line=command)
            if packages:
                summary = f"{packages[0]} +{len(packages) - 1} paket" if len(packages) > 1 else packages[0]
            elif "unattended-upgrade" in command.lower():
                summary = "Otomatik sistem güncellemesi"
            else:
                summary = "Paket işlemi"
            pixbuf = self._get_operation_pixbuf(packages)
            self.operations_store.append([pixbuf, pid, command, summary])
            total_count += 1

        if total_count > 0:
            self.operations_status.set_text(f"{total_count} işlem devam ediyor.")
            self._on_operations_selection_changed(self.operations_tree.get_selection())
        else:
            self.operations_status.set_text("Devam eden işlem görünmüyor.")
            self.operations_pause_btn.set_sensitive(False)
            self.operations_cancel_btn.set_sensitive(False)

    def _get_operation_pixbuf(self, packages: list[str]) -> GdkPixbuf.Pixbuf | None:
        size = 32
        if packages:
            pkg_names_lower = {p.lower() for p in packages}
            for app in self.applications:
                if app.package_name.lower() in pkg_names_lower or app.name.lower() in pkg_names_lower:
                    return self._get_app_pixbuf(app)
            theme = Gtk.IconTheme.get_default()
            for pkg in packages:
                for candidate in (pkg, pkg.lower()):
                    try:
                        return theme.load_icon(candidate, size, Gtk.IconLookupFlags.FORCE_SIZE)
                    except Exception:
                        pass
        theme = Gtk.IconTheme.get_default()
        try:
            return theme.load_icon("system-software-install", size, Gtk.IconLookupFlags.FORCE_SIZE)
        except Exception:
            pass
        try:
            return theme.load_icon("application-x-executable", size, Gtk.IconLookupFlags.FORCE_SIZE)
        except Exception:
            return None

    def _on_operations_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        has_sel = len(paths) == 1
        self.operations_cancel_btn.set_sensitive(has_sel)
        if has_sel:
            it = model.get_iter(paths[0])
            pid = model.get_value(it, _OC_PID)
            self.operations_pause_btn.set_sensitive(pid != "●")
        else:
            self.operations_pause_btn.set_sensitive(False)

    def _find_active_op_by_command(self, command: str) -> dict | None:
        return next((op for op in self._active_ops.values() if op["command"] == command), None)

    def _on_operations_pause(self, *_args) -> None:
        import signal as signal_mod
        import subprocess as sp
        selection = self.operations_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        it = model.get_iter(paths[0])
        pid = model.get_value(it, _OC_PID)
        if pid == "●":
            return  # pause not supported for in-app ops (button is disabled)
        summary = model.get_value(it, _OC_PACKAGES)
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"İşlem duraklatılsın mı? (PID {pid})",
        )
        dialog.format_secondary_text(
            f"{summary}\n\nDikkat: Çalışan bir APT/DPKG işlemini duraklatmak sistemi "
            "tutarsız bırakabilir."
        )
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            os.kill(int(pid), signal_mod.SIGSTOP)
        except PermissionError:
            r = sp.run(["pkexec", "/bin/kill", "-STOP", pid], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self._show_error_dialog(f"PID {pid} duraklatılamadı.\n{r.stderr.strip() or 'Yetki hatası.'}")
                return
        except (ProcessLookupError, ValueError):
            self._show_error_dialog(f"PID {pid} bulunamadı.")
            return
        self._refresh_operations_list()

    def _on_operations_cancel(self, *_args) -> None:
        import signal as signal_mod
        import subprocess as sp
        selection = self.operations_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        it = model.get_iter(paths[0])
        pid = model.get_value(it, _OC_PID)
        command = model.get_value(it, _OC_COMMAND)
        summary = model.get_value(it, _OC_PACKAGES)

        if pid == "●":
            op = self._find_active_op_by_command(command)
            cancel_fn = op.get("cancel_fn") if op else None
            if not cancel_fn:
                self._show_error_dialog("Bu işlem iptal edilemiyor.")
                return
            app_name = op["base_summary"] if op else command
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=f"Kurulum iptal edilsin mi?",
            )
            dialog.format_secondary_text(
                f"{app_name}\n\nKurulum işlemi durdurulacak. "
                "Flatpak için bu genellikle güvenlidir; APT işlemleri için "
                "'sudo dpkg --configure -a' gerekebilir."
            )
            response = dialog.run()
            dialog.destroy()
            if response == Gtk.ResponseType.OK:
                cancel_fn()
                GLib.timeout_add(800, self._refresh_operations_list)
            return

        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"İşlem iptal edilsin mi? (PID {pid})",
        )
        dialog.format_secondary_text(
            f"{summary}\n\nDikkat: Devam eden bir kurulum veya güncelleme yarıda kesilirse "
            "sistem tutarsız kalabilir."
        )
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        try:
            os.kill(int(pid), signal_mod.SIGTERM)
        except PermissionError:
            r = sp.run(["pkexec", "/bin/kill", "-TERM", pid], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self._show_error_dialog(f"PID {pid} iptal edilemedi.\n{r.stderr.strip() or 'Yetki hatası.'}")
                return
        except (ProcessLookupError, ValueError):
            self._show_error_dialog(f"PID {pid} bulunamadı.")
            return
        GLib.timeout_add(1500, self._refresh_operations_list)

    def _show_error_dialog(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Hata",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _on_package_selection_changed(self, selection: Gtk.TreeSelection) -> None:
        model, paths = selection.get_selected_rows()
        count = len(paths)
        has_sel = count > 0
        single_upgradable = False
        if count == 1:
            it = model.get_iter(paths[0])
            pkg: PackageInfo = model.get_value(it, _PC_PKG)
            single_upgradable = pkg.update_available if pkg else False
        any_upgradable = False
        for path in paths:
            it = model.get_iter(path)
            pkg = model.get_value(it, _PC_PKG)
            if pkg and pkg.update_available:
                any_upgradable = True
                break
        self.packages_update_btn.set_sensitive(has_sel and any_upgradable)
        self.packages_changelog_btn.set_sensitive(count == 1)
        self.packages_export_selected_btn.set_sensitive(has_sel)

    def _on_update_selected_packages(self, *_args) -> None:
        selection = self.packages_tree.get_selection()
        model, paths = selection.get_selected_rows()
        names = []
        for path in paths:
            it = model.get_iter(path)
            pkg: PackageInfo = model.get_value(it, _PC_PKG)
            if pkg and pkg.update_available:
                names.append(pkg.name)
        if not names:
            return
        lang = self.preferences.language
        self._run_packages_task(
            lambda: self.application_registry.update_packages(names),
            t(lang, "packages_update_done"),
            progress_title=t(lang, "packages_update_progress"),
        )

    def _on_update_all_packages(self, *_args) -> None:
        lang = self.preferences.language
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=t(lang, "packages_confirm_update_all"),
        )
        dialog.get_style_context().add_class("icon-settings-window")
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.YES:
            return
        upgradable = [p.name for p in self.packages if p.update_available]
        if not upgradable:
            return
        self._run_packages_task(
            lambda: self.application_registry.update_packages(upgradable),
            t(lang, "packages_update_done"),
            progress_title=t(lang, "packages_update_progress"),
        )

    def _on_package_changelog(self, *_args) -> None:
        selection = self.packages_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        it = model.get_iter(paths[0])
        pkg: PackageInfo = model.get_value(it, _PC_PKG)
        if not pkg:
            return
        lang = self.preferences.language

        def _fetch():
            return self.application_registry.apt_changelog(pkg.name)

        def _show(text):
            title = f"{t(lang, 'packages_changelog')} — {pkg.name}"
            if not text:
                text = t(lang, "changelog_none")
            dlg = Gtk.Dialog(title=title, transient_for=self, flags=Gtk.DialogFlags.MODAL)
            dlg.set_default_size(700, 500)
            dlg.get_style_context().add_class("icon-settings-window")
            dlg.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CLOSE)
            content = dlg.get_content_area()
            content.set_margin_top(12)
            content.set_margin_bottom(8)
            content.set_margin_start(12)
            content.set_margin_end(12)
            tv = Gtk.TextView()
            tv.set_editable(False)
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.get_buffer().set_text(text)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            sw.add(tv)
            content.pack_start(sw, True, True, 0)
            dlg.show_all()
            dlg.run()
            dlg.destroy()
            return False

        threading.Thread(
            target=lambda: GLib.idle_add(_show, _fetch()),
            daemon=True,
        ).start()

    def _save_export_txt(self, rows: list[dict], status_callback) -> None:
        """Open a save dialog and write rows as CSV. Each row: name, version, source."""
        import csv as _csv
        import io as _io
        lang = self.preferences.language
        dialog = Gtk.FileChooserDialog(
            title=t(lang, "export_selected_title"),
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(lang, "settings_save"), Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name("export.csv")
        csv_filter = Gtk.FileFilter()
        csv_filter.set_name("CSV (*.csv)")
        csv_filter.add_pattern("*.csv")
        dialog.add_filter(csv_filter)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        try:
            buf = _io.StringIO()
            writer = _csv.writer(buf)
            writer.writerow(["name", "version", "source"])
            for r in rows:
                writer.writerow([r["name"], r["version"], r["source"]])
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(buf.getvalue())
            status_callback(t(lang, "export_selected_done") + path, "#1f7a1f")
        except OSError as exc:
            status_callback(str(exc), "red")

    def _on_export_selected_applications(self, *_args) -> None:
        selection = self.applications_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        rows = []
        for path in paths:
            it = model.get_iter(path)
            app: UnifiedApplication = model.get_value(it, _AC_APP)
            if app:
                rows.append({"name": app.name, "version": app.version, "source": app.source})
        self._save_export_txt(rows, self._set_applications_status)

    def _on_export_selected_packages(self, *_args) -> None:
        selection = self.packages_tree.get_selection()
        model, paths = selection.get_selected_rows()
        if not paths:
            return
        rows = []
        for path in paths:
            it = model.get_iter(path)
            pkg: PackageInfo = model.get_value(it, _PC_PKG)
            if pkg:
                rows.append({"name": pkg.name, "version": pkg.version, "source": "apt"})
        self._save_export_txt(rows, lambda msg, color: self.packages_status.set_markup(
            f'<span color="{color}">{GLib.markup_escape_text(msg)}</span>'
        ))

    def _run_packages_task(
        self,
        task: "Callable[[], None]",
        success_message: str,
        progress_title: str = "",
    ) -> None:
        lang = self.preferences.language
        password_dlg = Gtk.Dialog(
            title=t(lang, "password_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        password_dlg.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        password_dlg.add_button(t(lang, "password_ok"), Gtk.ResponseType.OK)
        password_dlg.set_default_response(Gtk.ResponseType.OK)
        password_dlg.get_style_context().add_class("icon-settings-window")
        content = password_dlg.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(14)
        content.set_margin_bottom(8)
        content.set_margin_start(14)
        content.set_margin_end(14)
        msg_label = Gtk.Label(label=t(lang, "store_apt_password_message"))
        msg_label.set_xalign(0)
        msg_label.set_line_wrap(True)
        content.pack_start(msg_label, False, False, 0)
        pw_entry = Gtk.Entry()
        pw_entry.set_visibility(False)
        pw_entry.set_activates_default(True)
        content.pack_start(pw_entry, False, False, 0)
        password_dlg.show_all()
        resp = password_dlg.run()
        password = pw_entry.get_text()
        password_dlg.destroy()
        if resp != Gtk.ResponseType.OK or not password:
            return

        self.application_registry.set_sudo_password(password)

        progress = OperationProgressWindow(
            title=progress_title,
            message=progress_title,
            parent=self,
        )
        self.application_registry.runner.set_output_callback(
            lambda line: GLib.idle_add(progress.append_log, line)
        )
        progress.show_all()

        def _worker():
            err = None
            try:
                task()
            except AuthRequiredError:
                err = "auth"
            except BackendError as exc:
                err = str(exc)
            except Exception as exc:
                err = str(exc)
            GLib.idle_add(_done, err)

        def _done(err):
            self.application_registry.runner.set_output_callback(None)
            self.application_registry.set_sudo_password("")
            if err == "auth":
                short = t(lang, "store_apt_password_retry")
                progress.finish(False, short)
                self.packages_status.set_markup(
                    f'<span color="#cc0000">{GLib.markup_escape_text(short)}</span>'
                )
            elif err:
                short = self._short_task_error(err)
                progress.finish(False, err)
                self.packages_status.set_markup(
                    f'<span color="#cc0000">{GLib.markup_escape_text(short)}</span>'
                )
            else:
                progress.finish(True, success_message)
                self.packages_status.set_markup(
                    f'<span color="#1f7a1f">{GLib.markup_escape_text(success_message)}</span>'
                )
                self.reload_packages_async()
            return False

        threading.Thread(target=_worker, daemon=True).start()

    def _setup_keyboard_shortcuts(self) -> None:
        self.connect("key-press-event", self._on_key_press)

    def _on_key_press(self, _window: Gtk.Window, event: Gdk.EventKey) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        key = event.keyval
        if key == Gdk.KEY_F5:
            self.reload_applications_async()
            return True
        if key == Gdk.KEY_Delete and self.pages.get_current_page() == 0:
            sel = self.applications_tree.get_selection()
            model, paths = sel.get_selected_rows()
            if len(paths) == 1:
                app = model.get_value(model.get_iter(paths[0]), _AC_APP)
                if app:
                    self.on_remove_application(None, app)
            elif len(paths) > 1:
                self.on_bulk_remove_applications(None)
            return True
        if ctrl and key == Gdk.KEY_f:
            if self.pages.get_current_page() == 0:
                self.applications_search_entry.grab_focus()
            else:
                self.store_search_entry.grab_focus()
            return True
        return False

    def _update_category_combo(self) -> None:
        if not hasattr(self, "applications_category_combo"):
            return
        if getattr(self, "_updating_category_combo", False):
            return
        self._updating_category_combo = True
        try:
            current = self.applications_category_combo.get_active_id() or "__all__"
            categories: list[str] = sorted({
                app.category for app in self.applications if app.category
            })
            self.applications_category_combo.remove_all()
            lang = self.preferences.language
            self.applications_category_combo.append("__all__", t(lang, "applications_category_all"))
            for cat in categories:
                self.applications_category_combo.append(cat, cat)
            if current in {"__all__"} | set(categories):
                self.applications_category_combo.set_active_id(current)
            else:
                self.applications_category_combo.set_active(0)
                self.application_filter_category = "__all__"
        finally:
            self._updating_category_combo = False

    def _on_category_filter_changed(self, combo: Gtk.ComboBoxText) -> None:
        if getattr(self, "_updating_category_combo", False):
            return
        cat = combo.get_active_id() or "__all__"
        self.application_filter_category = cat
        self._render_applications_list()

    def on_export_application_list(self, _button) -> None:
        lang = self.preferences.language
        dialog = Gtk.FileChooserDialog(
            title=t(lang, "applications_export_title"),
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t(lang, "settings_save"), Gtk.ResponseType.OK)
        dialog.set_current_name("applications.json")
        json_filter = Gtk.FileFilter()
        json_filter.set_name(t(lang, "applications_export_filter_json"))
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)
        txt_filter = Gtk.FileFilter()
        txt_filter.set_name(t(lang, "applications_export_filter_txt"))
        txt_filter.add_pattern("*.txt")
        dialog.add_filter(txt_filter)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        try:
            import json as _json
            data = [
                {"name": app.name, "source": app.source, "version": app.version, "package": app.package_name}
                for app in self.applications
            ]
            if path.endswith(".txt"):
                content = "\n".join(f"{d['name']} ({d['source']}) {d['version']}" for d in data)
            else:
                content = _json.dumps(data, ensure_ascii=False, indent=2)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            self._set_applications_status(t(lang, "applications_export_done") + " " + path, "#1f7a1f")
        except OSError as exc:
            self._set_applications_status(str(exc), "red")

    def on_add_appimage(self, _button) -> None:
        lang = self.preferences.language
        dialog = Gtk.FileChooserDialog(
            title=t(lang, "appimage_register_title"),
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button("OK", Gtk.ResponseType.OK)
        ai_filter = Gtk.FileFilter()
        ai_filter.set_name(t(lang, "appimage_register_filter"))
        ai_filter.add_pattern("*.AppImage")
        ai_filter.add_pattern("*.appimage")
        dialog.add_filter(ai_filter)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        self._run_application_task(
            lambda: self.application_registry.register_appimage(path),
            "appimage_register_done",
            refresh_after=True,
        )

    def on_bulk_remove_applications(self, _button) -> None:
        sel = self.applications_tree.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            return
        apps = [model.get_value(model.get_iter(p), _AC_APP) for p in paths]
        apps = [a for a in apps if a is not None]
        if not apps:
            return
        lang = self.preferences.language
        dialog = Gtk.Dialog(
            title=t(lang, "applications_remove_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
        )
        dialog.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        remove_btn = dialog.add_button(t(lang, "applications_remove"), Gtk.ResponseType.OK)
        remove_btn.get_style_context().add_class("destructive-action")
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)
        names = ", ".join(a.name for a in apps[:5])
        if len(apps) > 5:
            names += f" (+{len(apps) - 5})"
        label = Gtk.Label(label=f"{len(apps)} uygulama kaldırılacak:\n{names}")
        label.set_line_wrap(True)
        label.set_xalign(0)
        content.pack_start(label, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return

        def _remove_all():
            for app in apps:
                self.application_registry.remove(app, purge=False)

        self._run_application_task(
            _remove_all,
            "applications_remove_done",
            refresh_after=True,
            show_progress=True,
            progress_title=t(lang, "applications_progress_remove"),
            progress_message=f"{len(apps)} uygulama",
        )

    def on_flatpak_permissions(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        try:
            perms = self.application_registry.flatpak_permissions(application.package_name)
        except Exception as exc:
            self._set_applications_status(str(exc), "red")
            return

        dialog = Gtk.Dialog(
            title=t(lang, "flatpak_permissions_title"),
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dialog.set_default_size(500, 400)
        reset_btn = dialog.add_button(t(lang, "flatpak_permissions_reset"), Gtk.ResponseType.APPLY)
        reset_btn.get_style_context().add_class("destructive-action")
        dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(14)
        content.set_margin_bottom(8)
        content.set_margin_start(14)
        content.set_margin_end(14)

        subtitle = Gtk.Label(label=t(lang, "flatpak_permissions_subtitle"))
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        content.pack_start(subtitle, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_monospace(True)
        buf = textview.get_buffer()
        if perms:
            lines = []
            for section, values in perms.items():
                lines.append(f"[{section}]")
                lines.extend(values)
            buf.set_text("\n".join(lines))
        else:
            buf.set_text(t(lang, "flatpak_permissions_none"))
        scrolled.add(textview)
        content.pack_start(scrolled, True, True, 0)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.APPLY:
            self._run_application_task(
                lambda: self.application_registry.flatpak_reset_permissions(application.package_name),
                "flatpak_permissions_reset_done",
                refresh_after=False,
            )

    def on_flatpak_rollback(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        self._set_applications_status(t(lang, "applications_loading"), "#666666")

        def _fetch():
            try:
                history = self.application_registry.flatpak_history(application.package_name)
            except Exception:
                history = []
            GLib.idle_add(_show_dialog, history)

        def _show_dialog(history: list[dict]) -> bool:
            if not history:
                self._set_applications_status(t(lang, "flatpak_rollback_no_history"), "#cc7a00")
                return False

            dialog = Gtk.Dialog(
                title=t(lang, "flatpak_rollback_title"),
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            )
            dialog.set_default_size(600, 360)
            rollback_btn = dialog.add_button(t(lang, "flatpak_rollback_btn"), Gtk.ResponseType.APPLY)
            rollback_btn.set_sensitive(False)
            dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

            content = dialog.get_content_area()
            content.set_spacing(8)
            content.set_margin_top(14)
            content.set_margin_bottom(8)
            content.set_margin_start(14)
            content.set_margin_end(14)

            subtitle = Gtk.Label(label=t(lang, "flatpak_rollback_subtitle"))
            subtitle.set_xalign(0)
            content.pack_start(subtitle, False, False, 0)

            store = Gtk.ListStore(str, str, str)  # date, version, commit
            for entry in history:
                store.append([entry.get("date", ""), entry.get("version", ""), entry.get("commit", "")])

            tree = Gtk.TreeView(model=store)
            tree.set_headers_visible(True)
            for col_idx, col_title_key in enumerate(("flatpak_rollback_col_date", "flatpak_rollback_col_version", "flatpak_rollback_col_commit")):
                renderer = Gtk.CellRendererText()
                col = Gtk.TreeViewColumn(t(lang, col_title_key), renderer, text=col_idx)
                tree.append_column(col)

            def _on_sel(sel: Gtk.TreeSelection) -> None:
                _, it = sel.get_selected()
                rollback_btn.set_sensitive(it is not None)

            tree.get_selection().connect("changed", _on_sel)

            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(200)
            scroll.add(tree)
            content.pack_start(scroll, True, True, 0)
            dialog.show_all()

            response = dialog.run()
            if response == Gtk.ResponseType.APPLY:
                _, it = tree.get_selection().get_selected()
                if it:
                    commit = store.get_value(it, 2)
                    dialog.destroy()
                    self._run_application_task(
                        lambda: self.application_registry.flatpak_rollback(application.package_name, commit),
                        "flatpak_rollback_done",
                        refresh_after=True,
                        show_progress=True,
                        progress_title=t(lang, "flatpak_rollback_title"),
                        progress_message=application.name,
                    )
                    return False
            dialog.destroy()
            self._set_applications_status("", "#666666")
            return False

        threading.Thread(target=_fetch, daemon=True).start()

    def on_show_changelog(self, _button, application: UnifiedApplication) -> None:
        lang = self.preferences.language
        self._set_applications_status(t(lang, "applications_loading"), "#666666")

        def _fetch():
            try:
                changelog = self.application_registry.apt_changelog(application.package_name)
            except Exception:
                changelog = ""
            GLib.idle_add(_show, changelog)

        def _show(text: str) -> bool:
            dialog = Gtk.Dialog(
                title=t(lang, "changelog_title") + f" — {application.name}",
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
            )
            dialog.set_default_size(680, 500)
            dialog.add_button(t(lang, "dialog_close"), Gtk.ResponseType.CLOSE)

            content = dialog.get_content_area()
            content.set_margin_top(14)
            content.set_margin_bottom(8)
            content.set_margin_start(14)
            content.set_margin_end(14)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_min_content_height(350)
            textview = Gtk.TextView()
            textview.set_editable(False)
            textview.set_monospace(True)
            textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            buf = textview.get_buffer()
            buf.set_text(text.strip() if text.strip() else t(lang, "changelog_none"))
            scrolled.add(textview)
            content.pack_start(scrolled, True, True, 0)

            dialog.show_all()
            dialog.run()
            dialog.destroy()
            self._set_applications_status("", "#666666")
            return False

        threading.Thread(target=_fetch, daemon=True).start()
