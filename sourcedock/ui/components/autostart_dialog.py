"""Başlangıç Uygulamaları (XDG Autostart) Yönetim Penceresi."""

from __future__ import annotations

from pathlib import Path
import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from sourcedock.backend.autostart import (
    AutostartEntry,
    create_user_autostart_entry,
    detect_autostart_mode,
    list_autostart_entries,
    remove_user_autostart_entry,
    run_autostart_entry,
    toggle_autostart_entry,
    unwrap_autostart_exec,
    update_autostart_entry,
)
from sourcedock.i18n import t
from sourcedock.ui.components.common import icon_button, icon_text_button, prepare_dialog, set_status


def _resolve_entry_icon_name(entry: AutostartEntry, installed_apps: list) -> str:
    """Autostart girdisi için en uygun ikon adını veya dosya yolunu bulur."""
    raw = (entry.icon or "").strip()
    if raw and raw != "application-x-executable":
        return raw
    base_name = entry.filename.removesuffix(".desktop").casefold()
    entry_name = entry.name.casefold()
    exec_lower = (entry.exec_cmd or "").casefold()
    for app in installed_apps or ():
        app_desktop = Path(getattr(app, "desktop_file", "") or "").name.casefold()
        if app_desktop and app_desktop == entry.filename.casefold():
            if getattr(app, "icon", ""):
                return app.icon
        if getattr(app, "name", "").casefold() == entry_name and getattr(app, "icon", ""):
            return app.icon
        pkg = (getattr(app, "package_name", "") or "").casefold()
        if pkg and len(pkg) >= 3 and (pkg == base_name or pkg in exec_lower):
            if getattr(app, "icon", ""):
                return app.icon
    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon(base_name):
        return base_name
    return raw or "application-x-executable"


def _load_autostart_icon(icon_name: str, size: int = 32) -> GdkPixbuf.Pixbuf | None:
    """Dosya yolu veya tema adından başlangıç uygulaması ikonunu yükler."""
    raw = (icon_name or "").strip()
    if raw:
        p = Path(raw)
        if p.is_file():
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(p), size, size, True)
            except Exception:
                pass
        theme = Gtk.IconTheme.get_default()
        if theme is not None:
            candidates = [raw, raw.lower()]
            if "." in p.name:
                candidates.append(p.stem)
                candidates.append(p.stem.lower())
            for candidate in dict.fromkeys(candidates):
                try:
                    return theme.load_icon(candidate, size, Gtk.IconLookupFlags.FORCE_SIZE)
                except Exception:
                    continue
    theme = Gtk.IconTheme.get_default()
    if theme is not None:
        for fallback in ("application-x-executable", "system-run-symbolic"):
            try:
                return theme.load_icon(fallback, size, Gtk.IconLookupFlags.FORCE_SIZE)
            except Exception:
                continue
    return None


class AutostartDialog(Gtk.Dialog):
    """Kullanıcı ve sistem başlangıç uygulamalarını ayrı sekmelerde yöneten pencere."""

    def __init__(self, parent, language: str = "tr", on_close=None):
        super().__init__(
            title=t(language, "autostart_dialog_title"),
            transient_for=None,
            modal=False,
            destroy_with_parent=False,
        )
        self.parent_window = parent
        self.language = language
        self.on_close = on_close
        self._closed = False
        self._entries: list[AutostartEntry] = []

        def _on_destroy(_w):
            self._closed = True
            if callable(self.on_close):
                self.on_close()

        self.connect("destroy", _on_destroy)
        prepare_dialog(self, width=820, height=600, independent=True)
        self.add_button(t(language, "dialog_close"), Gtk.ResponseType.CLOSE)
        self.connect("response", lambda _d, _r: self.destroy())

        content = self.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(16)
        content.set_margin_end(16)

        subtitle = Gtk.Label(label=t(language, "autostart_dialog_desc"), xalign=0)
        subtitle.set_line_wrap(True)
        subtitle.get_style_context().add_class("dim-label")
        content.pack_start(subtitle, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(t(language, "autostart_search_placeholder"))
        self.search_entry.connect("changed", lambda _e: self._render_entries())
        toolbar.pack_start(self.search_entry, True, True, 0)

        add_btn = Gtk.Button()
        icon_text_button(
            add_btn,
            "list-add-symbolic",
            t(language, "autostart_add_btn"),
            t(language, "autostart_add_btn"),
        )
        add_btn.get_style_context().add_class("suggested-action")
        add_btn.connect("clicked", lambda _b: self._open_entry_dialog())
        toolbar.pack_end(add_btn, False, False, 0)

        refresh_btn = Gtk.Button()
        icon_button(refresh_btn, "view-refresh-symbolic", t(language, "applications_refresh"))
        refresh_btn.connect("clicked", lambda _b: self._reload())
        toolbar.pack_end(refresh_btn, False, False, 0)
        content.pack_start(toolbar, False, False, 0)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        content.pack_start(self.notebook, True, True, 0)

        self.user_list_box = self._make_tab_list(t(language, "autostart_tab_user"))
        self.system_list_box = self._make_tab_list(t(language, "autostart_tab_system"))

        self.status_lbl = Gtk.Label(xalign=0)
        self.status_lbl.set_line_wrap(True)
        content.pack_start(self.status_lbl, False, False, 0)

        self.show_all()
        self._reload()

    def _make_tab_list(self, title: str) -> Gtk.Box:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(4)
        box.set_margin_end(4)
        scroller.add(box)
        lbl = Gtk.Label(label=title)
        lbl.set_margin_start(6)
        lbl.set_margin_end(6)
        lbl.set_margin_top(4)
        lbl.set_margin_bottom(4)
        self.notebook.append_page(scroller, lbl)
        return box

    def _reload(self) -> None:
        self._entries = list_autostart_entries()
        self._render_entries()

    def _render_entries(self) -> None:
        query = self.search_entry.get_text().strip().casefold()
        user_entries = [
            e for e in self._entries
            if not e.is_system
            and (not query or query in e.name.casefold() or query in e.exec_cmd.casefold() or query in e.comment.casefold())
        ]
        sys_entries = [
            e for e in self._entries
            if e.is_system
            and (not query or query in e.name.casefold() or query in e.exec_cmd.casefold() or query in e.comment.casefold())
        ]
        self._populate_list(self.user_list_box, user_entries)
        self._populate_list(self.system_list_box, sys_entries)

    def _populate_list(self, container: Gtk.Box, entries: list[AutostartEntry]) -> None:
        for child in list(container.get_children()):
            container.remove(child)

        if not entries:
            empty_lbl = Gtk.Label(label=t(self.language, "autostart_empty"))
            empty_lbl.set_margin_top(28)
            empty_lbl.get_style_context().add_class("dim-label")
            container.pack_start(empty_lbl, False, False, 0)
            container.show_all()
            return

        installed_apps = getattr(self.parent_window, "applications", [])
        for entry in entries:
            frame = Gtk.Frame()
            frame.get_style_context().add_class("summary-card")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.set_margin_top(10)
            row.set_margin_bottom(10)
            row.set_margin_start(12)
            row.set_margin_end(12)
            frame.add(row)

            resolved_icon = _resolve_entry_icon_name(entry, installed_apps)
            pixbuf = _load_autostart_icon(resolved_icon, 32)
            icon_img = (
                Gtk.Image.new_from_pixbuf(pixbuf)
                if pixbuf is not None
                else Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR)
            )
            row.pack_start(icon_img, False, False, 0)

            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name_lbl = Gtk.Label(xalign=0)
            name_lbl.set_markup(f"<b>{GLib.markup_escape_text(entry.name)}</b>")
            title_row.pack_start(name_lbl, False, False, 0)

            scope_lbl = Gtk.Label(
                label=t(self.language, "autostart_badge_system" if entry.is_system else "autostart_badge_user")
            )
            scope_lbl.get_style_context().add_class("package-badge")
            title_row.pack_start(scope_lbl, False, False, 0)
            info_box.pack_start(title_row, False, False, 0)

            if entry.comment:
                comment_lbl = Gtk.Label(label=entry.comment, xalign=0)
                comment_lbl.set_line_wrap(True)
                comment_lbl.get_style_context().add_class("dim-label")
                info_box.pack_start(comment_lbl, False, False, 0)

            if entry.exec_cmd:
                cmd_lbl = Gtk.Label(xalign=0)
                cmd_lbl.set_markup(
                    f"<span size='small' alpha='75%'>{GLib.markup_escape_text(t(self.language, 'autostart_cmd_prefix', cmd=entry.exec_cmd))}</span>"
                )
                cmd_lbl.set_line_wrap(True)
                cmd_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                info_box.pack_start(cmd_lbl, False, False, 0)

            row.pack_start(info_box, True, True, 0)

            # Aksiyon butonları: Çalıştır, Düzenle, (Kullanıcıysa) Sil, Anahtar
            if entry.exec_cmd:
                run_btn = Gtk.Button()
                icon_button(run_btn, "media-playback-start-symbolic", t(self.language, "autostart_run_tooltip"))
                run_btn.get_style_context().add_class("flat")

                def _on_run(_b, target=entry):
                    try:
                        run_autostart_entry(target)
                        set_status(self.status_lbl, t(self.language, "autostart_run_started", name=target.name))
                    except Exception as exc:
                        set_status(self.status_lbl, str(exc), error=True)

                run_btn.connect("clicked", _on_run)
                row.pack_end(run_btn, False, False, 0)

            edit_btn = Gtk.Button()
            icon_button(edit_btn, "document-edit-symbolic", t(self.language, "autostart_edit_tooltip"))
            edit_btn.get_style_context().add_class("flat")
            edit_btn.connect("clicked", lambda _b, target=entry: self._open_entry_dialog(target))
            row.pack_end(edit_btn, False, False, 0)

            if not entry.is_system:
                del_btn = Gtk.Button()
                icon_button(del_btn, "user-trash-symbolic", t(self.language, "autostart_remove_tooltip"))
                del_btn.get_style_context().add_class("flat")

                def _on_delete(_b, target=entry):
                    try:
                        remove_user_autostart_entry(target)
                        self._reload()
                    except Exception as exc:
                        set_status(self.status_lbl, str(exc), error=True)

                del_btn.connect("clicked", _on_delete)
                row.pack_end(del_btn, False, False, 0)

            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            guard = {"updating": True}
            sw.set_active(entry.enabled)
            guard["updating"] = False

            def _on_toggled(_sw, state: bool, target=entry, g=guard):
                if g["updating"]:
                    return False
                try:
                    toggle_autostart_entry(target, bool(state))
                    target.enabled = bool(state)
                    return False
                except Exception as exc:
                    g["updating"] = True
                    _sw.set_active(not bool(state))
                    g["updating"] = False
                    set_status(self.status_lbl, str(exc), error=True)
                    return True

            sw.connect("state-set", _on_toggled)
            row.pack_end(sw, False, False, 0)
            container.pack_start(frame, False, False, 0)

        container.show_all()

    def _open_entry_dialog(self, entry: AutostartEntry | None = None) -> None:
        lang = self.language
        is_edit = entry is not None
        diag = Gtk.Dialog(
            title=t(lang, "autostart_edit_title" if is_edit else "autostart_add_title"),
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        prepare_dialog(diag, width=560, height=380, independent=False)
        diag.add_button(t(lang, "password_cancel"), Gtk.ResponseType.CANCEL)
        ok_btn = diag.add_button(
            t(lang, "settings_save" if is_edit else "autostart_add_confirm"),
            Gtk.ResponseType.OK,
        )
        ok_btn.get_style_context().add_class("suggested-action")

        area = diag.get_content_area()
        area.set_spacing(10)
        area.set_margin_top(14)
        area.set_margin_bottom(14)
        area.set_margin_start(16)
        area.set_margin_end(16)

        grid = Gtk.Grid(column_spacing=16, row_spacing=10)
        area.pack_start(grid, False, False, 0)

        row_idx = 0
        selected_icon = {"name": entry.icon if entry else "application-x-executable"}

        name_entry = Gtk.Entry()
        name_entry.set_hexpand(True)
        cmd_entry = Gtk.Entry()
        cmd_entry.set_hexpand(True)

        if not is_edit:
            apps = sorted(
                [a for a in getattr(self.parent_window, "applications", []) if getattr(a, "executable", "")],
                key=lambda a: a.name.casefold(),
            )
            preset_lbl = Gtk.Label(label=t(lang, "autostart_add_preset"), xalign=0)
            preset_btn = Gtk.MenuButton()
            preset_btn.set_hexpand(True)
            preset_btn_lbl = Gtk.Label(label=t(lang, "autostart_add_custom"), xalign=0)
            preset_btn_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            preset_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            preset_btn_box.pack_start(preset_btn_lbl, True, True, 0)
            preset_btn_box.pack_end(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU), False, False, 0)
            preset_btn.add(preset_btn_box)

            popover = Gtk.Popover()
            pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pop_box.set_margin_top(8)
            pop_box.set_margin_bottom(8)
            pop_box.set_margin_start(8)
            pop_box.set_margin_end(8)
            pop_search = Gtk.SearchEntry()
            pop_search.set_placeholder_text(t(lang, "applications_search_placeholder"))
            pop_box.pack_start(pop_search, False, False, 0)

            pop_scroll = Gtk.ScrolledWindow()
            pop_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            pop_scroll.set_size_request(320, 220)
            pop_scroll.set_min_content_height(220)
            pop_scroll.set_max_content_height(220)
            pop_list = Gtk.ListBox()
            pop_list.set_selection_mode(Gtk.SelectionMode.NONE)
            pop_scroll.add(pop_list)
            pop_box.pack_start(pop_scroll, True, True, 0)
            pop_box.show_all()
            popover.add(pop_box)
            preset_btn.set_popover(popover)

            def _fill_preset_list(query_text: str = "") -> None:
                for child in list(pop_list.get_children()):
                    pop_list.remove(child)
                q = query_text.strip().casefold()
                for app in apps:
                    if q and q not in app.name.casefold():
                        continue
                    row = Gtk.ListBoxRow()
                    btn = Gtk.Button()
                    btn.set_relief(Gtk.ReliefStyle.NONE)
                    btn.get_style_context().add_class("flat")
                    lbl = Gtk.Label(label=f"{app.name} ({app.source.upper()})", xalign=0)
                    lbl.set_ellipsize(Pango.EllipsizeMode.END)
                    btn.add(lbl)

                    def _pick(_b, chosen=app):
                        name_entry.set_text(chosen.name)
                        cmd_entry.set_text(chosen.executable)
                        selected_icon["name"] = chosen.icon or "application-x-executable"
                        preset_btn_lbl.set_text(f"{chosen.name} ({chosen.source.upper()})")
                        popover.popdown()

                    btn.connect("clicked", _pick)
                    row.add(btn)
                    pop_list.add(row)
                pop_list.show_all()

            pop_search.connect("changed", lambda e: _fill_preset_list(e.get_text()))
            _fill_preset_list("")

            grid.attach(preset_lbl, 0, row_idx, 1, 1)
            grid.attach(preset_btn, 1, row_idx, 1, 1)
            row_idx += 1

        name_lbl = Gtk.Label(label=t(lang, "autostart_add_name"), xalign=0)
        if entry is not None:
            name_entry.set_text(entry.name)

        cmd_lbl = Gtk.Label(label=t(lang, "autostart_add_cmd"), xalign=0)
        if entry is not None:
            cmd_entry.set_text(unwrap_autostart_exec(entry.exec_cmd))

        mode_lbl = Gtk.Label(label=t(lang, "autostart_add_mode"), xalign=0)
        mode_combo = Gtk.ComboBoxText()
        mode_combo.set_hexpand(True)
        mode_combo.connect("scroll-event", lambda *_args: True)
        mode_combo.append("normal", t(lang, "autostart_mode_normal"))
        mode_combo.append("background", t(lang, "autostart_mode_background"))
        mode_combo.append("terminal", t(lang, "autostart_mode_terminal"))
        mode_combo.set_active_id(detect_autostart_mode(entry) if entry is not None else "normal")

        comment_lbl = Gtk.Label(label=t(lang, "autostart_add_comment"), xalign=0)
        comment_entry = Gtk.Entry()
        comment_entry.set_hexpand(True)
        if entry is not None and entry.comment:
            comment_entry.set_text(entry.comment)

        grid.attach(name_lbl, 0, row_idx, 1, 1)
        grid.attach(name_entry, 1, row_idx, 1, 1)
        grid.attach(cmd_lbl, 0, row_idx + 1, 1, 1)
        grid.attach(cmd_entry, 1, row_idx + 1, 1, 1)
        grid.attach(mode_lbl, 0, row_idx + 2, 1, 1)
        grid.attach(mode_combo, 1, row_idx + 2, 1, 1)
        grid.attach(comment_lbl, 0, row_idx + 3, 1, 1)
        grid.attach(comment_entry, 1, row_idx + 3, 1, 1)

        diag.show_all()
        if diag.run() == Gtk.ResponseType.OK:
            try:
                if entry is not None:
                    update_autostart_entry(
                        entry,
                        name_entry.get_text(),
                        cmd_entry.get_text(),
                        mode=mode_combo.get_active_id() or "normal",
                        comment=comment_entry.get_text(),
                    )
                else:
                    create_user_autostart_entry(
                        name_entry.get_text(),
                        cmd_entry.get_text(),
                        mode=mode_combo.get_active_id() or "normal",
                        icon=selected_icon["name"],
                        comment=comment_entry.get_text(),
                    )
                    self.notebook.set_current_page(0)
                self._reload()
            except Exception as exc:
                set_status(self.status_lbl, str(exc), error=True)
        diag.destroy()
        if not self._closed:
            self.present()
