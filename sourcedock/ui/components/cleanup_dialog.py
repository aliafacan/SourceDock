"""Birleşik Disk ve Önbellek Temizleme Diyaloğu."""

from __future__ import annotations

import threading
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from sourcedock.backend.disk_cleanup import DiskCleanupPlan, apply_disk_cleanup, format_bytes, plan_disk_cleanup
from sourcedock.core.errors import AuthRequiredError
from sourcedock.i18n import t
from sourcedock.ui.components.common import prepare_dialog, set_status


class DiskCleanupDialog(Gtk.Dialog):
    """APT, Snap ve Flatpak artıklarını detaylarıyla gösteren ve seçerek temizleyen diyalog."""

    def __init__(self, parent, registry, language: str = "tr", on_cleaned=None, on_close=None):
        super().__init__(
            title=t(language, "cleanup_dialog_title"),
            transient_for=None,
            modal=False,
            destroy_with_parent=False,
        )
        self.parent_window = parent
        self.registry = registry
        self.language = language
        self.on_cleaned = on_cleaned
        self.on_close = on_close
        self.plan: DiskCleanupPlan | None = None
        self._closed = False

        def _on_destroy(_w):
            self._closed = True
            if callable(self.on_close):
                self.on_close()

        self.connect("destroy", _on_destroy)

        prepare_dialog(self, width=720, height=540, independent=True)
        self.add_button(t(language, "dialog_close"), Gtk.ResponseType.CLOSE)
        self.clean_btn = self.add_button(t(language, "cleanup_action_btn"), Gtk.ResponseType.OK)
        self.clean_btn.get_style_context().add_class("suggested-action")
        self.clean_btn.set_sensitive(False)

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(16)
        content.set_margin_end(16)

        subtitle = Gtk.Label(label=t(language, "cleanup_dialog_desc"), xalign=0)
        subtitle.set_line_wrap(True)
        subtitle.get_style_context().add_class("dim-label")
        content.pack_start(subtitle, False, False, 0)

        self.stack = Gtk.Stack()
        content.pack_start(self.stack, True, True, 0)

        # Loading state
        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        loading_box.set_valign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.start()
        loading_lbl = Gtk.Label(label=t(language, "cleanup_scanning"))
        loading_box.pack_start(spinner, False, False, 0)
        loading_box.pack_start(loading_lbl, False, False, 0)
        self.stack.add_named(loading_box, "loading")

        # Content state
        self.items_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.items_box)
        self.stack.add_named(scroller, "content")

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_no_show_all(True)
        self.progress_bar.set_visible(False)
        content.pack_start(self.progress_bar, False, False, 0)

        self.status_lbl = Gtk.Label(xalign=0)
        self.status_lbl.set_line_wrap(True)
        content.pack_start(self.status_lbl, False, False, 0)

        self.connect("response", self._on_response)
        self.show_all()
        self.stack.set_visible_child_name("loading")
        self._scan_async()

    def _scan_async(self) -> None:
        native_mgr = getattr(getattr(self.registry, "native_provider", None), "source", "apt")

        def worker():
            plan = plan_disk_cleanup(self.registry.runner, native_manager=native_mgr)
            GLib.idle_add(self._on_scan_finished, plan)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_finished(self, plan: DiskCleanupPlan) -> bool:
        if self._closed:
            return False
        self.plan = plan
        for child in list(self.items_box.get_children()):
            self.items_box.remove(child)

        lang = self.language
        self.checks: dict[str, Gtk.CheckButton] = {}
        self.item_checks: dict[str, list[tuple[object, Gtk.CheckButton]]] = {
            "apt_autoremove": [],
            "snap_old": [],
            "flatpak": [],
        }

        if not plan.has_anything:
            empty_lbl = Gtk.Label(label=t(lang, "cleanup_nothing_found"))
            empty_lbl.set_margin_top(24)
            empty_lbl.get_style_context().add_class("dim-label")
            self.items_box.pack_start(empty_lbl, False, False, 0)
            self.clean_btn.set_sensitive(False)
            self.items_box.show_all()
            self.stack.set_visible_child_name("content")
            return False

        def _add_card(
            key: str,
            title: str,
            detail: str,
            detail_items: list[tuple[object, str, bool]] | None = None,
            selectable_children: bool = True,
        ) -> None:
            frame = Gtk.Frame()
            frame.get_style_context().add_class("summary-card")
            card_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card_vbox.set_margin_top(10)
            card_vbox.set_margin_bottom(10)
            card_vbox.set_margin_start(12)
            card_vbox.set_margin_end(12)
            frame.add(card_vbox)

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card_vbox.pack_start(row, False, False, 0)

            cb = Gtk.CheckButton()
            cb.set_active(True)
            cb.set_valign(Gtk.Align.CENTER)
            row.pack_start(cb, False, False, 0)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t_lbl = Gtk.Label(xalign=0)
            t_lbl.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
            d_lbl = Gtk.Label(label=detail, xalign=0)
            d_lbl.set_line_wrap(True)
            d_lbl.get_style_context().add_class("dim-label")
            vbox.pack_start(t_lbl, False, False, 0)
            vbox.pack_start(d_lbl, False, False, 0)
            row.pack_start(vbox, True, True, 0)

            self.checks[key] = cb

            if detail_items:
                toggle_btn = Gtk.ToggleButton()
                toggle_btn.set_relief(Gtk.ReliefStyle.NONE)
                toggle_btn.get_style_context().add_class("flat")
                toggle_btn.set_halign(Gtk.Align.START)
                toggle_btn.set_margin_start(24)
                toggle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                arrow_img = Gtk.Image.new_from_icon_name("pan-end-symbolic", Gtk.IconSize.MENU)
                toggle_lbl = Gtk.Label(label=t(lang, "cleanup_show_details", count=len(detail_items)))
                toggle_box.pack_start(arrow_img, False, False, 0)
                toggle_box.pack_start(toggle_lbl, False, False, 0)
                toggle_btn.add(toggle_box)
                card_vbox.pack_start(toggle_btn, False, False, 0)

                detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                detail_box.set_margin_start(32)
                detail_box.set_margin_top(4)
                detail_box.set_margin_bottom(4)
                detail_box.set_no_show_all(True)
                detail_box.set_visible(False)
                card_vbox.pack_start(detail_box, False, False, 0)

                def _on_details_toggled(btn: Gtk.ToggleButton, box=detail_box, img=arrow_img):
                    expanded = btn.get_active()
                    img.set_from_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic", Gtk.IconSize.MENU)
                    box.set_visible(expanded)
                    if expanded:
                        for c in box.get_children():
                            c.show_all()

                toggle_btn.connect("toggled", _on_details_toggled)

                child_guard = {"syncing": False}
                for obj, label_text, active in detail_items:
                    if selectable_children:
                        item_cb = Gtk.CheckButton(label=label_text)
                        item_cb.set_active(active)
                        detail_box.pack_start(item_cb, False, False, 0)
                        self.item_checks[key].append((obj, item_cb))

                        def _on_child_toggled(_w, target_cb=cb, k=key):
                            if child_guard["syncing"]:
                                return
                            child_guard["syncing"] = True
                            any_active = any(c.get_active() for _, c in self.item_checks[k])
                            target_cb.set_active(any_active)
                            child_guard["syncing"] = False

                        item_cb.connect("toggled", _on_child_toggled)
                    else:
                        lbl = Gtk.Label(label=f"• {label_text}", xalign=0)
                        lbl.get_style_context().add_class("dim-label")
                        detail_box.pack_start(lbl, False, False, 0)

                if selectable_children:
                    def _on_master_toggled(master_cb, k=key):
                        if child_guard["syncing"]:
                            return
                        child_guard["syncing"] = True
                        state = master_cb.get_active()
                        for _, child_cb in self.item_checks[k]:
                            child_cb.set_active(state)
                        child_guard["syncing"] = False

                    cb.connect("toggled", _on_master_toggled)

            self.items_box.pack_start(frame, False, False, 0)

        if plan.apt_cache_files > 0:
            cache_details = [
                (name, f"{name} ({format_bytes(sz)})", True)
                for name, sz in plan.apt_cache_items[:80]
            ]
            _add_card(
                "apt_cache",
                t(lang, "cleanup_apt_cache_title"),
                t(lang, "cleanup_apt_cache_desc", count=plan.apt_cache_files, size=format_bytes(plan.apt_cache_bytes)),
                detail_items=cache_details,
                selectable_children=False,
            )
        if plan.apt_autoremove_packages:
            auto_details = [(pkg, pkg, True) for pkg in plan.apt_autoremove_packages]
            _add_card(
                "apt_autoremove",
                t(lang, "cleanup_apt_autoremove_title"),
                t(lang, "cleanup_apt_autoremove_desc", count=len(plan.apt_autoremove_packages)),
                detail_items=auto_details,
                selectable_children=True,
            )
        if plan.snap_old_revisions:
            snap_details = [
                (item, f"{item.name} (rev {item.revision}) — {format_bytes(item.size_bytes)}", True)
                for item in plan.snap_old_revisions
            ]
            _add_card(
                "snap_old",
                t(lang, "cleanup_snap_old_title"),
                t(lang, "cleanup_snap_old_desc", count=len(plan.snap_old_revisions), size=format_bytes(plan.snap_bytes)),
                detail_items=snap_details,
                selectable_children=True,
            )
        if plan.flatpak_refs:
            fp_details = [
                (ref, f"[{ref.scope}] {ref.ref}", True)
                for ref in plan.flatpak_refs
            ]
            _add_card(
                "flatpak",
                t(lang, "cleanup_flatpak_title"),
                t(lang, "cleanup_flatpak_desc", count=len(plan.flatpak_refs)),
                detail_items=fp_details,
                selectable_children=True,
            )

        self.clean_btn.set_sensitive(True)
        self.items_box.show_all()
        self.stack.set_visible_child_name("content")
        return False

    def _collect_selections(self) -> dict:
        clean_apt_cache = self.checks["apt_cache"].get_active() if "apt_cache" in self.checks else False
        sel_auto = [obj for obj, cb in self.item_checks["apt_autoremove"] if cb.get_active()]
        clean_apt_autoremove = bool(sel_auto) if self.item_checks["apt_autoremove"] else (
            self.checks["apt_autoremove"].get_active() if "apt_autoremove" in self.checks else False
        )
        sel_snap = [obj for obj, cb in self.item_checks["snap_old"] if cb.get_active()]
        clean_snap_old = bool(sel_snap)
        sel_fp = tuple(obj for obj, cb in self.item_checks["flatpak"] if cb.get_active())
        clean_flatpak = bool(sel_fp)
        return {
            "clean_apt_cache": clean_apt_cache,
            "clean_apt_autoremove": clean_apt_autoremove,
            "clean_snap_old": clean_snap_old,
            "clean_flatpak": clean_flatpak,
            "selected_apt_autoremove": sel_auto,
            "selected_snap_revisions": sel_snap,
            "selected_flatpak_refs": sel_fp,
        }

    def _on_response(self, _dialog, response_id: int) -> None:
        if response_id != Gtk.ResponseType.OK:
            self.destroy()
            return
        if self.plan is None:
            return
        sel = self._collect_selections()
        if not any((sel["clean_apt_cache"], sel["clean_apt_autoremove"], sel["clean_snap_old"], sel["clean_flatpak"])):
            self.destroy()
            return

        self.clean_btn.set_sensitive(False)
        self.progress_bar.set_fraction(0.05)
        self.progress_bar.set_text(t(self.language, "cleanup_running"))
        self.progress_bar.show()
        set_status(self.status_lbl, t(self.language, "cleanup_running"))

        def _update_progress(frac: float, msg: str) -> None:
            def _apply():
                if not self._closed:
                    self.progress_bar.set_fraction(max(0.05, min(1.0, frac)))
                    self.progress_bar.set_text(f"{int(frac * 100)}% — {msg}")
                return False
            GLib.idle_add(_apply)

        def worker(pwd: str | None = None):
            try:
                if pwd:
                    self.registry.runner.set_sudo_password(pwd)
                apply_disk_cleanup(self.registry.runner, self.plan, on_progress=_update_progress, **sel)
                GLib.idle_add(self._on_cleanup_done, True, None)
            except AuthRequiredError as auth_err:
                GLib.idle_add(self._on_auth_required, auth_err, sel)
            except Exception as exc:
                GLib.idle_add(self._on_cleanup_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_auth_required(self, auth_err, sel: dict) -> bool:
        if self._closed:
            return False
        ask = getattr(self.parent_window, "_ask_sudo_password", None)
        pwd = ask(retry=getattr(auth_err, "password_failed", False)) if ask else None
        if not pwd:
            self.clean_btn.set_sensitive(True)
            self.progress_bar.hide()
            set_status(self.status_lbl, t(self.language, "status_cancelled"), error=True)
            return False

        def _update_progress(frac: float, msg: str) -> None:
            def _apply():
                if not self._closed:
                    self.progress_bar.set_fraction(max(0.05, min(1.0, frac)))
                    self.progress_bar.set_text(f"{int(frac * 100)}% — {msg}")
                return False
            GLib.idle_add(_apply)

        def retry_worker():
            try:
                self.registry.runner.set_sudo_password(pwd)
                apply_disk_cleanup(self.registry.runner, self.plan, on_progress=_update_progress, **sel)
                GLib.idle_add(self._on_cleanup_done, True, None)
            except Exception as exc:
                GLib.idle_add(self._on_cleanup_done, False, str(exc))

        threading.Thread(target=retry_worker, daemon=True).start()
        return False

    def _on_cleanup_done(self, ok: bool, error: str | None) -> bool:
        if self._closed:
            return False
        if ok:
            if callable(self.on_cleaned):
                self.on_cleaned()
            if hasattr(self.parent_window, "show_toast"):
                self.parent_window.show_toast(t(self.language, "cleanup_done"), level="success")
            self.destroy()
        else:
            self.clean_btn.set_sensitive(True)
            set_status(self.status_lbl, error or "Error", error=True)
        return False
