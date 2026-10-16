"""Responsive navigation and global search around the existing GTK pages."""

import gi
from pathlib import Path

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from sourcedock.constants import APP_VERSION
from sourcedock.i18n import t
from sourcedock.ui.components.common import icon_button
from sourcedock.ui.components.toast import ToastHost

PAGE_KEYS = {0: "nav_installed", 1: "nav_discover", 2: "nav_packages", 3: "nav_operations", 4: "nav_updates"}


class ShellViewMixin:
    def _build_window_shell(self):
        self._syncing_global_search = False
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.set_title("SourceDock")
        self.header_search = Gtk.SearchEntry()
        self.header_search.set_width_chars(24)
        self.header_search.set_max_width_chars(28)
        self.header_search.connect("search-changed", self._on_global_search_changed)
        self.header_search.connect("activate", self._on_global_search_activate)
        self.header.pack_start(self.header_search)
        self.header_updates_btn = Gtk.Button()
        self.header_updates_btn.connect("clicked", lambda _button: self.pages.set_current_page(4))
        self.header.pack_end(self.header_updates_btn)
        self.header_operations_btn = Gtk.Button()
        self.header_operations_btn.connect("clicked", lambda _button: self.pages.set_current_page(3))
        self.header.pack_end(self.header_operations_btn)
        self.set_titlebar(self.header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.root = root
        self.toast_host = ToastHost(root, language=self.preferences.language)
        self.add(self.toast_host)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.get_style_context().add_class("sidebar")
        self.sidebar.set_size_request(220, -1)
        root.pack_start(self.sidebar, False, False, 0)
        self._sidebar_collapsed_override = None
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        brand.set_margin_top(16)
        brand.set_margin_bottom(24)
        logo = Path(__file__).resolve().parents[3] / "assets" / "sourcedock.png"
        image = (
            Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(logo), 40, 40, True))
            if logo.exists()
            else Gtk.Image.new_from_icon_name("sourcedock", Gtk.IconSize.DIALOG)
        )
        brand.pack_start(image, False, False, 0)
        self.brand_label = Gtk.Label(label="SourceDock")
        self.brand_label.get_style_context().add_class("brand-title")
        brand.pack_start(self.brand_label, False, False, 0)
        self.sidebar_toggle = Gtk.Button()
        self.sidebar_toggle.get_style_context().add_class("sidebar-brand-button")
        self.sidebar_toggle.set_halign(Gtk.Align.START)
        self.sidebar_toggle.add(brand)
        self.sidebar_toggle.connect("clicked", self._on_sidebar_toggle)
        self.sidebar.pack_start(self.sidebar_toggle, False, False, 0)
        self.nav_buttons = {}
        self.nav_labels = {}
        for index, icon in (
            (1, "system-search-symbolic"),
            (0, "view-grid-symbolic"),
            (4, "software-update-available-symbolic"),
            (3, "view-list-symbolic"),
            (2, "package-x-generic-symbolic"),
        ):
            button, label = self._sidebar_button(icon)
            button.connect("clicked", lambda _button, page=index: self.pages.set_current_page(page))
            self.sidebar.pack_start(button, False, False, 0)
            self.nav_buttons[index] = button
            self.nav_labels[index] = label
        self.sidebar.pack_start(Gtk.Box(), True, True, 0)
        self.local_install_btn, self.local_install_label = self._sidebar_button("list-add-symbolic")
        self.local_install_btn.connect("clicked", self.on_install_local_package)
        self.sidebar.pack_start(self.local_install_btn, False, False, 0)
        self.settings_btn, self.settings_label = self._sidebar_button("preferences-system-symbolic")
        self.settings_btn.connect("clicked", self.on_open_settings)
        self.sidebar.pack_start(self.settings_btn, False, False, 0)
        self.help_btn, self.help_label = self._sidebar_button("help-browser-symbolic")
        self.help_btn.connect("clicked", self.on_open_help)
        self.sidebar.pack_start(self.help_btn, False, False, 0)
        self.sidebar_version = Gtk.Label(label=APP_VERSION)
        self.sidebar_version.get_style_context().add_class("dim-label")
        self.sidebar_version.set_margin_top(16)
        self.sidebar.pack_start(self.sidebar_version, False, False, 0)
        root.pack_start(self.pages, True, True, 0)
        self.pages.set_show_tabs(False)
        self.pages.set_show_border(False)
        self.pages.get_style_context().add_class("page-content")
        self.connect("size-allocate", self._on_shell_size_allocate)
        self._compact_sidebar = None

    def _on_sidebar_toggle(self, _button) -> None:
        """Toggle the wide-screen sidebar without overriding narrow layout."""
        if self.get_size()[0] < 1200:
            self._refresh_sidebar_toggle_text()
            return
        self._sidebar_collapsed_override = not bool(self._compact_sidebar)
        self._set_sidebar_compact(self._sidebar_collapsed_override)

    def _refresh_sidebar_toggle_text(self) -> None:
        if not hasattr(self, "sidebar_toggle"):
            return
        width = self.get_size()[0]
        if width < 1200:
            key = "sidebar_compact_locked"
        else:
            key = "sidebar_expand" if self._compact_sidebar else "sidebar_collapse"
        label = t(self.preferences.language, key)
        self.sidebar_toggle.set_tooltip_text(label)
        self.sidebar_toggle.get_accessible().set_name(label)

    def _set_sidebar_compact(self, compact: bool) -> None:
        if compact == self._compact_sidebar:
            self._refresh_sidebar_toggle_text()
            return
        self._compact_sidebar = compact
        self.sidebar.set_size_request(64 if compact else 220, -1)
        for label in (
            *self.nav_labels.values(),
            self.local_install_label,
            self.settings_label,
            self.help_label,
            self.brand_label,
            self.sidebar_version,
        ):
            label.set_no_show_all(compact)
            label.set_visible(not compact)
        self._refresh_sidebar_toggle_text()
        # The size-request change can otherwise be applied one allocation
        # later. Keep the next page capture and user interaction in sync.
        self.sidebar.queue_resize()
        parent = self.sidebar.get_parent()
        if parent is not None:
            parent.queue_resize()
            parent.check_resize()
        GLib.idle_add(self._queue_sidebar_reflow)

    def _sidebar_button(self, icon):
        button = Gtk.Button()
        button.get_style_context().add_class("nav-button")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
        label = Gtk.Label()
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(label, True, True, 0)
        button.add(box)
        return button, label

    def _on_shell_size_allocate(self, _window, allocation):
        # Keep the compact sidebar active through the 1024px class of usable
        # client widths. A higher threshold prevents fractional text scaling
        # from crossing the breakpoint and forcing the wide sidebar back in.
        compact = self.get_size()[0] < 1200
        if not compact and self._sidebar_collapsed_override is not None:
            compact = self._sidebar_collapsed_override
        self._set_sidebar_compact(compact)

    def _queue_sidebar_reflow(self):
        if self.sidebar.get_visible():
            self.sidebar.queue_resize()
            parent = self.sidebar.get_parent()
            if parent is not None:
                parent.queue_resize()
                parent.check_resize()
        return False

    def _refresh_shell_texts(self):
        lang = self.preferences.language
        for index, label in self.nav_labels.items():
            text = t(lang, PAGE_KEYS[index])
            label.set_text(text)
            self.nav_buttons[index].set_tooltip_text(text)
            self.nav_buttons[index].get_accessible().set_name(text)
        for label, button, key in (
            (self.local_install_label, self.local_install_btn, "install_package_btn"),
            (self.settings_label, self.settings_btn, "settings"),
            (self.help_label, self.help_btn, "help"),
        ):
            text = t(lang, key)
            label.set_text(text)
            button.set_tooltip_text(text)
            button.get_accessible().set_name(text)
        self.header_search.set_placeholder_text(t(lang, "global_search"))
        self.header_search.get_accessible().set_name(t(lang, "global_search"))
        self._refresh_sidebar_toggle_text()
        self._refresh_shell_page()
        icon_button(self.header_operations_btn, "emblem-synchronizing-symbolic", t(lang, "nav_operations"))
        self._refresh_update_count()
        if hasattr(self, "toast_host") and self.toast_host is not None:
            self.toast_host.language = lang


    def _refresh_shell_page(self, page: int | None = None):
        index = self.pages.get_current_page() if page is None else page
        self.header.set_title(t(self.preferences.language, PAGE_KEYS.get(index, "nav_installed")))
        self.header.set_subtitle("")
        self._sync_header_search_for_page(index)
        for page, button in self.nav_buttons.items():
            context = button.get_style_context()
            context.remove_class("nav-active")
            if page == index:
                context.add_class("nav-active")

    def _search_entry_for_page(self, page: int):
        return {
            0: self.applications_search_entry,
            1: self.store_search_entry,
            2: self.packages_search_entry,
        }.get(page)

    def _sync_header_search_for_page(self, page: int) -> None:
        """Keep the visible search field scoped to the active searchable page."""
        target = self._search_entry_for_page(page)
        self._suppress_global_search_changed = True
        try:
            self.header_search.set_sensitive(target is not None)
            self.header_search.set_text(target.get_text() if target is not None else "")
            self.header_search.set_tooltip_text(
                t(self.preferences.language, "global_search")
                if target is not None
                else t(self.preferences.language, "search_unavailable_page")
            )
        finally:
            self._suppress_global_search_changed = False

    def _refresh_update_count(self):
        if not hasattr(self, "header_updates_btn"):
            return
        count = len(getattr(self, "update_items", []))
        self.header_updates_btn.set_label(str(count) if count else "")
        self.header_updates_btn.set_image(
            Gtk.Image.new_from_icon_name("software-update-available-symbolic", Gtk.IconSize.BUTTON)
        )
        self.header_updates_btn.set_always_show_image(True)
        self.header_updates_btn.set_tooltip_text(
            t(self.preferences.language, "updates_count", count=count)
        )
        self.header_updates_btn.get_accessible().set_name(
            t(self.preferences.language, "updates_count", count=count)
        )

    def _on_global_search_changed(self, entry):
        if self._suppress_global_search_changed:
            return
        page = self.pages.get_current_page()
        target = self._search_entry_for_page(page)
        cursor_position = entry.get_position() if entry is self.header_search else None
        if target is not None and target.get_text() != entry.get_text():
            self._syncing_global_search = True
            try:
                target.set_text(entry.get_text())
            finally:
                self._syncing_global_search = False
            # Page-local entries are intentionally hidden; GTK does not emit
            # their search-changed signal while hidden, so update their view
            # explicitly and keep one search request per header change.
            handler = {
                0: self.on_applications_search_changed,
                1: self._on_store_search_changed,
                2: self._on_packages_search_changed,
            }.get(page)
            if handler is not None:
                handler(target)
        if cursor_position is not None:
            entry.set_position(min(cursor_position, len(entry.get_text())))

    def _on_global_search_activate(self, _entry):
        if self.pages.get_current_page() not in (0, 1, 2):
            self.pages.set_current_page(1)
            self.store_search_entry.set_text(self.header_search.get_text())
        if self.pages.get_current_page() == 1:
            self.on_store_search()

    def show_toast(self, message: str, level: str = "info", timeout: int = 4):
        """Display a non-blocking transient toast notification."""
        if hasattr(self, "toast_host") and self.toast_host is not None:
            return self.toast_host.show_toast(message, level=level, timeout=timeout)
        return None

    def hide_toast(self) -> None:
        """Dismiss active toast notification if any."""
        if hasattr(self, "toast_host") and self.toast_host is not None:
            self.toast_host.hide_toast()

