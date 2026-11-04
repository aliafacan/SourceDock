#!/usr/bin/env python3
"""İşlem ve kurulum ilerleme penceresi (OperationProgressWindow)."""

from __future__ import annotations

from collections.abc import Callable
import re
import shlex
import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # pyright: ignore[reportMissingModuleSource]


from sourcedock.i18n import t
from sourcedock.ui.components.common import make_window_movable


class OperationProgressWindow(Gtk.Window):
    """Küçültülebilir işlem penceresi; ana görünüm özet, detaylar isteğe bağlı."""

    def __init__(
        self,
        title: str,
        message: str,
        parent: Gtk.Window,
        on_progress: Callable[[float, str], None] | None = None,
        language: str = "tr",
        cancel_fn: Callable[[], bool] | None = None,
        show_details_by_default: bool = False,
    ) -> None:
        super().__init__(title=title)
        self.language = language
        self.set_default_size(460, 190)
        self.set_resizable(True)
        self.set_deletable(True)
        self.set_skip_taskbar_hint(False)
        self.set_skip_pager_hint(False)
        self.set_decorated(True)
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_position(Gtk.WindowPosition.CENTER)
        make_window_movable(self, independent=True)
        self.get_style_context().add_class("icon-settings-window")
        self._last_measurement = 0.0
        self._phase_started = time.monotonic()
        self._last_output_at = self._phase_started
        self._running_provider = ""
        self._progress_watch = GLib.timeout_add_seconds(1, self._expire_measurement)
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

        self._title_label = Gtk.Label(label=t(self.language, "progress_preparing"))
        self._title_label.set_xalign(0)
        self._title_label.set_ellipsize(Pango.EllipsizeMode.END)
        content.pack_start(self._title_label, False, False, 0)

        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0)
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._status_label.get_style_context().add_class("dim-label")
        content.pack_start(self._status_label, False, False, 0)

        self._details_expander = Gtk.Expander(label=t(self.language, "progress_details"))
        self._details_expander.set_expanded(show_details_by_default)
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

        self._cancel_fn = cancel_fn
        if cancel_fn is not None:
            self._cancel_btn = Gtk.Button(label=t(self.language, "btn_cancel"))
            self._cancel_btn.connect("clicked", self._on_cancel_clicked)
            button_row.pack_start(self._cancel_btn, False, False, 0)
        else:
            self._cancel_btn = None

        self._minimize_btn = Gtk.Button(label=t(self.language, "progress_minimize"))
        self._minimize_btn.connect("clicked", lambda _button: self.iconify())
        button_row.pack_start(self._minimize_btn, False, False, 0)

        self._close_btn = Gtk.Button(label=t(self.language, "progress_close"))
        self._close_btn.get_style_context().add_class("suggested-action")
        self._close_btn.set_sensitive(False)
        self._close_btn.connect("clicked", lambda _button: self.destroy())
        button_row.pack_start(self._close_btn, False, False, 0)

        self._pulse_source: int | None = GLib.timeout_add(80, self._pulse)
        self.connect("destroy", self._on_destroy)
        self.show_all()

    def _short_error(self, message: str) -> str:
        lowered = message.lower()
        if "lock-frontend" in lowered or "kilidi alınamadı" in lowered or "kilitlenemiyor" in lowered:
            return t(self.language, "progress_apt_busy_desc")
        if "dpkg" in lowered and "configure -a" in lowered:
            return t(self.language, "progress_dpkg_interrupted")
        if "access denied" in lowered or "sudo ile dene" in lowered:
            return t(self.language, "progress_auth_needed")
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), message.strip())
        return first_line[:180]

    def _on_destroy(self, *_args):
        self._stop_pulse()
        if self._progress_watch:
            GLib.source_remove(self._progress_watch)
            self._progress_watch = None

    def _expire_measurement(self):
        if self._done:
            self._progress_watch = None
            return False
        if self._last_measurement and time.monotonic() - self._last_measurement > 5:
            self._start_pulse()
            self._last_measurement = 0.0
        if self._running_provider and time.monotonic() - self._last_output_at > 3:
            elapsed = max(0, int(time.monotonic() - self._phase_started))
            self._status_label.set_text(t(
                self.language, "progress_running_elapsed", source=self._running_provider,
                elapsed=f"{elapsed // 60}:{elapsed % 60:02d}",
            ))
        return True

    def _pulse(self) -> bool:
        self._progress.pulse()
        return True

    def _start_pulse(self) -> None:
        self._progress.set_text("")
        self._progress.set_show_text(False)
        self._progress.set_fraction(0.0)
        if self._pulse_source is None:
            self._pulse_source = GLib.timeout_add(80, self._pulse)

    def _stop_pulse(self) -> None:
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None

    def _set_activity_phase(self, title: str, status: str) -> None:
        self._start_pulse()
        self._title_label.set_text(title)
        self._status_label.set_text(status)

    def append_log(self, line: str) -> None:
        if self._done or not line.strip():
            return
        if line.startswith("SOURCEDOCK_PHASE "):
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "queued":
                self._set_activity_phase(t(self.language, "progress_queued"), "")
            elif len(parts) >= 2 and parts[1] == "authorizing":
                self._set_activity_phase(t(self.language, "progress_authorizing"), "")
            elif len(parts) >= 3 and parts[1] == "running":
                self._running_provider = parts[2]
                self._phase_started = time.monotonic()
                self._last_output_at = self._phase_started
                self._set_activity_phase(t(self.language, "progress_running"), self._running_provider)
            return
        self._last_output_at = time.monotonic()
        # Terminal redraw bars are represented by the single GTK progress bar.
        # Keep diagnostics, phases and errors, without repeating ASCII bars.
        terminal_progress = bool(re.search(r"[█▉▊▋▌▍▎▏■░▒▓━═]{2,}|^\s*\d+(?:[.,]\d+)?%\s+.*(?:/s|\d+:\d+)", line))
        if not terminal_progress:
            self._append_detail(line)
        if self._consume_package_progress(line):
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
        if self._log_buf.get_line_count() > 2000:
            self._log_buf.delete(self._log_buf.get_start_iter(), self._log_buf.get_iter_at_line(500))

    def _consume_package_progress(self, line: str) -> bool:
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
        clean = re.sub(r"\s+", " ", clean).strip()
        lowered = clean.lower()
        step = re.search(r"(?:Updating|Güncelleniyor|Installing|Kuruluyor)\s+\d+/\d+", clean, re.I)
        if step:
            self._title_label.set_text(step.group(0))


        # Each percentage belongs to its own phase. Get: reports the size
        # of an item being fetched, not the bytes actually received.
        phases = (
            (r"Arşiv güvenli|çalıştırılabilir dosyası aranıyor", "progress_installing"),
            (r"Uygulama menüsü|Portable uygulama kaydı", "progress_configuring"),
            (r"^(?:Preparing to unpack|Unpacking|Paket açılıyor)|paketi açılıyor", "progress_installing"),
            (r"^(?:Setting up|Processing triggers)|(?:ayarlanıyor|yapılandırılıyor|tetikleyiciler işleniyor)", "progress_configuring"),
            (r"^(?:Reading package lists|Building dependency tree|Reading state information|Paket listeleri okunuyor|Bağımlılık ağacı)", "progress_calculating_deps"),
            (r"^(?:Fetched|İndirilen|Alınan):? \d", "progress_install_preparing"),
        )
        for pattern, key in phases:
            if re.search(pattern, clean, re.I):
                self._set_activity_phase(t(self.language, key), clean)
                return True
        apt_percent = re.match(r"^(\d{1,3})%\s+\[", clean)
        dpkg_percent = re.match(r"^Progress:\s*\[\s*(\d{1,3})%\s*\]", clean)
        if apt_percent or dpkg_percent:
            match = apt_percent or dpkg_percent
            percent = min(100, int(match.group(1)))
            self._title_label.set_text(t(self.language, "progress_downloading" if apt_percent else "progress_installing"))
            self._stop_pulse()
            self._last_measurement = time.monotonic()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            return True

        provider_percent = re.search(r"(?:^|\s)(\d{1,3}(?:\.\d+)?)\s*%", clean)
        if self._running_provider and provider_percent:
            percent = max(0.0, min(100.0, float(provider_percent.group(1))))
            self._stop_pulse()
            self._last_measurement = time.monotonic()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent:g}")
            self._progress.set_show_text(True)
            status = re.sub(r"[\[\]|█▉▊▋▌▍▎▏■░▒▓━═]+", " ", clean)
            status = re.sub(r"(?:^|\s)\d{1,3}(?:\.\d+)?\s*%", " ", status)
            self._status_label.set_text(re.sub(r"\s+", " ", status).strip()[:180])
            return True

        if step:
            return True

        fp_bar = re.search(r"[\[|]\s*[=■▌█▇▆▅▄▃▂▁\s]*[\]|]\s*(\d{1,3})\s*%", clean)
        if fp_bar:
            percent = max(0, min(100, int(fp_bar.group(1))))
            self._stop_pulse()
            self._last_measurement = time.monotonic()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            speed_match = re.search(r"(\d[\d.]*\s*(?:MB|KB|GB)/s)", clean, re.IGNORECASE)
            if speed_match:
                self._status_label.set_text(speed_match.group(1))
            return True

        fp_app = re.match(r"(?:Installing|Kuruluyor)\s+app/([^/\s]+)", clean, re.IGNORECASE)
        if fp_app:
            pkg = fp_app.group(1)
            self._set_activity_phase(
                f"{t(self.language, 'progress_installing')}: {pkg}",
                t(self.language, "progress_flatpak_unpacking"),
            )
            return True

        fp_rt = re.match(r"(?:Installing|Kuruluyor)\s+runtime/([^/\s]+)", clean, re.IGNORECASE)
        if fp_rt:
            self._set_activity_phase(
                f"{t(self.language, 'progress_dependency')}: {fp_rt.group(1)}",
                t(self.language, "progress_runtime_installing"),
            )
            return True

        if re.search(r"(?:updating|güncelleniyor)\s+(?:metadata\s+for\s+)?(?:remote\s+)?'?\w+'?", lowered):
            self._set_activity_phase(
                t(self.language, "progress_repo_updating"),
                t(self.language, "progress_flatpak_repo_refreshing"),
            )
            return True

        if lowered.startswith("downloading ") or lowered.startswith("indiriliyor "):
            url = clean.split(" ", 1)[1] if " " in clean else ""
            fname = url.rstrip("/").split("/")[-1][:60] if url else ""
            self._set_activity_phase(
                t(self.language, "progress_downloading"),
                fname or t(self.language, "progress_flatpak_fetching"),
            )
            return True

        snap_pct = re.search(r"\b(\d{1,3})%", clean)
        if snap_pct and re.search(r"[kKmMgG][bB]/?s|→|snap", clean, re.IGNORECASE):
            percent = max(0, min(100, int(snap_pct.group(1))))
            self._stop_pulse()
            self._last_measurement = time.monotonic()
            self._progress.set_fraction(percent / 100)
            self._progress.set_text(f"%{percent}")
            self._progress.set_show_text(True)
            return True

        if lowered.startswith("apt meşgul:") or lowered.startswith("apt busy:"):
            self._set_activity_phase(
                t(self.language, "progress_apt_busy"), self._summarize_apt_busy_line(clean)
            )
            return True
        if "otomatik devam edilecek" in lowered or "automatically continue" in lowered:
            if not self._status_label.get_text().startswith(
                "APT meşgul:"
            ) and not self._status_label.get_text().startswith("APT busy:"):
                self._set_activity_phase(t(self.language, "progress_apt_waiting"), clean)
            return True
        if "apt kilidi boşaldı" in lowered or "apt lock released" in lowered:
            self._set_activity_phase(
                t(self.language, "progress_apt_unlocked_title"), t(self.language, "progress_apt_resuming")
            )
            return True
        if (
            "lock-frontend" in lowered
            or "kilidi alınamadı" in lowered
            or "önbellek kilidi bekleniyor" in lowered
        ):
            self._set_activity_phase(
                t(self.language, "progress_apt_busy"),
                t(self.language, "progress_apt_busy_desc"),
            )
            return True

        summary_match = re.search(
            r"(?P<upgrade>\d+)\s+paket yükseltilecek,\s*(?P<new>\d+)\s+yeni paket kurulacak",
            lowered,
        )
        if summary_match:
            self._install_items_total = int(summary_match.group("upgrade")) + int(summary_match.group("new"))
            self._download_items_total = self._install_items_total
            unit = t(self.language, "progress_packages_unit")
            self._set_activity_phase(
                t(self.language, "progress_update_preparing"),
                f"{self._install_items_total} {unit}.",
            )
            return True

        total_match = re.search(
            r"(?:(?P<cached_num>[0-9][0-9.,]*)\s*(?P<cached_unit>[kmgt]?b)/)?(?P<total_num>[0-9][0-9.,]*)\s*(?P<total_unit>[kmgt]?b)\s+arşiv",
            clean,
            re.IGNORECASE,
        )
        if total_match:
            if total_match.group("cached_num") and total_match.group("cached_unit"):
                self._download_total_kib = self._human_size_to_kib(
                    total_match.group("cached_num"), total_match.group("cached_unit")
                )
            else:
                self._download_total_kib = self._human_size_to_kib(
                    total_match.group("total_num"), total_match.group("total_unit")
                )
            self._download_seen_kib = 0
            self._download_seen_items = 0
            self._title_label.set_text(t(self.language, "progress_download_preparing"))
            self._update_download_status()
            return True

        download_match = re.search(
            r"^(?:İndir|Get):\s*(\d+)\s+(.+?)\[([0-9][0-9.,]*)\s*([kmgt]?b)\]", clean, re.IGNORECASE
        )
        if download_match:
            index = int(download_match.group(1))
            package = self._package_name_from_apt_download(download_match.group(2))
            size_kib = self._human_size_to_kib(download_match.group(3), download_match.group(4))
            if index > self._download_seen_items:
                self._download_seen_items = index
                self._download_seen_kib += size_kib
            self._current_package = package
            self._title_label.set_text(f"{t(self.language, 'progress_downloading')}: {package}")
            self._update_download_status()
            return True

        return False

    def _summarize_progress_line(self, line: str) -> str:
        clean = re.sub(r"\s+", " ", line).strip()
        lowered = clean.lower()
        if not clean or lowered.startswith("warning: apt does not have") or lowered.startswith("n: "):
            return ""
        # Some privileged helpers can echo sudo's authentication probe while
        # the actual package transaction continues. Keep that diagnostic in
        # Details, but do not make the live operation look like a failure.
        if lowered.startswith("sudo:") and ("password" in lowered or "parola" in lowered):
            return ""
        if "paket listeleri okunuyor" in lowered or "reading package lists" in lowered:
            return t(self.language, "progress_reading_lists")
        if "bağımlılık ağacı" in lowered or "building dependency tree" in lowered:
            return t(self.language, "progress_calculating_deps")
        if "durum bilgisi" in lowered or "reading state information" in lowered:
            return t(self.language, "progress_reading_states")
        if "yükseltme hesaplanıyor" in lowered or "calculating upgrade" in lowered:
            return t(self.language, "progress_calculating_upgrade")
        if "yapacak bir şey yok" in lowered or "nothing to do" in lowered:
            return t(self.language, "progress_nothing_to_do")
        if clean.startswith(("E:", "hata:", "error:")):
            return t(self.language, "progress_failed")
        return clean

    def _summarize_apt_busy_line(self, line: str) -> str:
        lower = line.lower()
        packages = self._packages_from_apt_command(line)
        if packages:
            first = packages[0]
            rest = len(packages) - 1
            action = t(self.language, "applications_progress_update")
            if " remove " in lower or " purge " in lower:
                action = t(self.language, "applications_progress_remove")
            elif " install " in lower and "--only-upgrade" not in lower:
                action = t(self.language, "progress_installing")
            unit = t(self.language, "progress_packages_unit")
            suffix = f" +{rest} {unit}" if rest > 0 else ""
            return f"APT: {first}{suffix} {action}."
        if "unattended-upgrade" in lower:
            return t(self.language, "progress_apt_busy_auto")
        pid_match = re.search(r"pid\s+\d+:\s*([^;]+)", line, re.IGNORECASE)
        if pid_match:
            command = pid_match.group(1).strip()
            return f"APT: {command[:120]}"
        return t(self.language, "progress_apt_busy_other")

    def _packages_from_apt_command(self, line: str) -> list[str]:
        matches = re.findall(r"(?:apt-get|apt|nala)\s+(.+?)(?:;|$)", line)
        ignore_tokens = {
            "sudo",
            "-n",
            "-s",
            "-y",
            "-q",
            "install",
            "upgrade",
            "full-upgrade",
            "dist-upgrade",
            "remove",
            "purge",
            "autoremove",
            "--only-upgrade",
            "--",
            "apt-get",
            "apt",
            "nala",
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
        self._start_pulse()
        self._status_label.set_text(self._current_package or t(self.language, "progress_downloading"))

    def _package_name_from_apt_download(self, body: str) -> str:
        tokens = body.split()
        arch_tokens = {"all", "amd64", "arm64", "i386", "armhf"}
        for index in range(len(tokens) - 2, 1, -1):
            if tokens[index] in arch_tokens and tokens[index - 1] not in arch_tokens:
                return tokens[index - 1]
        return t(self.language, "progress_packages_unit")

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

    def _fire_progress(self) -> None:
        if not self._on_progress:
            return
        fraction = self._progress.get_fraction()
        label = self._title_label.get_text()
        self._on_progress(fraction, label)

    def finish(self, success: bool, message: str) -> None:
        if self._done:
            return
        self._done = True
        self._stop_pulse()
        self._progress.set_fraction(1.0 if success else 0.0)
        self._progress.set_text("%100" if success else "")
        self._progress.set_show_text(success)
        self._title_label.set_text(
            t(self.language, "progress_done") if success else t(self.language, "progress_failed")
        )
        status = message if success else self._short_error(message)
        self._status_label.set_text(status)
        self._status_label.get_style_context().remove_class("success-text")
        self._status_label.get_style_context().remove_class("error-text")
        self._status_label.get_style_context().add_class("success-text" if success else "error-text")
        self._append_detail(message)
        self._fire_progress()
        self._close_btn.set_sensitive(True)
        self._close_btn.grab_focus()
        if hasattr(self, "_cancel_btn") and self._cancel_btn is not None:
            self._cancel_btn.set_visible(False)
        if success:
            GLib.timeout_add(2000, self._auto_close)

    def _on_cancel_clicked(self, _button=None) -> None:
        if self._cancel_fn:
            ok = self._cancel_fn()
            if ok:
                if getattr(self, "_cancel_btn", None) is not None:
                    self._cancel_btn.set_sensitive(False)
                    self._cancel_btn.set_label(t(self.language, "progress_cancelling"))
            else:
                if getattr(self, "_cancel_btn", None) is not None:
                    self._cancel_btn.set_sensitive(False)
                self._status_label.set_text(t(self.language, "cancel_critical"))

    def _auto_close(self) -> bool:
        if self._done:
            self.destroy()
        return False

    def _on_delete_event(self, _window: Gtk.Window, _event) -> bool:
        if not self._done:
            if self._cancel_fn is not None:
                self._on_cancel_clicked()
                return True
            self.iconify()
            return True
        return False
