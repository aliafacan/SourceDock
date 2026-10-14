"""Small native widgets shared across the application screens."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk, Pango


def icon_button(button, icon_name: str, tooltip: str) -> None:
    button.set_label("")
    button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    button.set_always_show_image(True)
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    button.get_style_context().add_class("icon-button")


def set_status(label, message: str, error: bool = False) -> None:
    label.set_text(message)
    context = label.get_style_context()
    context.remove_class("error-text")
    context.remove_class("dim-label")
    context.add_class("error-text" if error else "dim-label")


def style_tree_view(tree: Gtk.TreeView) -> None:
    """Keep dense tables easy to scan with separators and row striping."""
    tree.set_rules_hint(True)
    tree.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
    tree.get_style_context().add_class("data-table")


class ContentState(Gtk.Stack):
    def __init__(self, content):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_named(content, "content")
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_halign(Gtk.Align.CENTER)
        panel.set_valign(Gtk.Align.CENTER)
        panel.set_margin_start(24)
        panel.set_margin_end(24)
        self.icon = Gtk.Image.new_from_icon_name("system-search-symbolic", Gtk.IconSize.DIALOG)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(32, 32)
        self.title = Gtk.Label()
        self.title.get_style_context().add_class("state-title")
        self.body = Gtk.Label()
        self.body.set_line_wrap(True)
        self.body.set_max_width_chars(48)
        self.body.set_justify(Gtk.Justification.CENTER)
        self.body.get_style_context().add_class("dim-label")
        for widget in (self.icon, self.spinner, self.title, self.body):
            panel.pack_start(widget, False, False, 0)
        self.add_named(panel, "state")
        self.show_all()
        self.show_content()

    def show_content(self):
        self.spinner.stop()
        self.set_visible_child_name("content")

    def show_state(self, title: str, body: str = "", loading: bool = False, error: bool = False):
        self.title.set_text(title)
        self.body.set_text(body)
        self.icon.set_from_icon_name(
            "dialog-warning-symbolic" if error else "system-search-symbolic", Gtk.IconSize.DIALOG
        )
        self.icon.set_visible(not loading)
        self.spinner.set_visible(loading)
        self.spinner.start() if loading else self.spinner.stop()
        self.set_visible_child_name("state")


class AppCard(Gtk.Button):
    def __init__(self, result, pixbuf, installed, action, language, variants=()):
        from sourcedock.i18n import t

        super().__init__()
        self.get_style_context().add_class("app-card")
        self.set_size_request(250, 212)
        self.set_hexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        header = Gtk.Box(spacing=12)
        image = (
            Gtk.Image.new_from_pixbuf(pixbuf)
            if pixbuf
            else Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.DIALOG)
        )
        image.set_pixel_size(56)
        header.pack_start(image, False, False, 0)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name = Gtk.Label(label=result.name, xalign=0)
        name.set_line_wrap(True)
        name.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        name.set_max_width_chars(24)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_lines(2)
        name.get_style_context().add_class("app-name")
        title_box.pack_start(name, False, False, 0)
        if result.publisher:
            publisher = Gtk.Label(label=result.publisher, xalign=0)
            publisher.set_ellipsize(Pango.EllipsizeMode.END)
            publisher.set_max_width_chars(24)
            publisher.get_style_context().add_class("dim-label")
            title_box.pack_start(publisher, False, False, 0)
        header.pack_start(title_box, True, True, 0)
        box.pack_start(header, False, False, 0)
        description = Gtk.Label(label=result.description or "", xalign=0)
        description.set_line_wrap(True)
        description.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        description.set_max_width_chars(28)
        description.set_ellipsize(Pango.EllipsizeMode.END)
        description.set_lines(2)
        description.get_style_context().add_class("dim-label")
        box.pack_start(description, True, True, 0)

        source_names = [result.source]
        source_names.extend(variant.source for variant in variants if variant.source not in source_names)
        source_labels = [t(language, f"store_source_{source}") for source in source_names]
        source = Gtk.Label(label="  ·  ".join(source_labels), xalign=0)
        source.set_ellipsize(Pango.EllipsizeMode.END)
        source.set_max_width_chars(28)
        source.get_style_context().add_class("source-badge")
        box.pack_start(source, False, False, 0)

        footer = Gtk.Box(spacing=8)
        if variants:
            variant_label = Gtk.Label(
                label=t(language, "store_sources_count", count=len(source_names)), xalign=0
            )
            variant_label.get_style_context().add_class("dim-label")
            footer.pack_start(variant_label, True, True, 0)
        else:
            footer.pack_start(Gtk.Box(), True, True, 0)
        action_label = (
            t(language, "store_installed_badge") if installed else t(language, "store_open_details")
        )
        action_label_widget = Gtk.Label(label=action_label)
        action_label_widget.get_style_context().add_class("card-action")
        footer.pack_end(action_label_widget, False, False, 0)
        footer.pack_end(
            Gtk.Image.new_from_icon_name(
                "emblem-ok-symbolic" if installed else "go-next-symbolic", Gtk.IconSize.BUTTON
            ),
            False,
            False,
            0,
        )
        box.pack_end(footer, False, False, 0)
        self.add(box)
        self.set_tooltip_text(t(language, "applications_details"))
        self.get_accessible().set_name(result.name + ", " + ", ".join(source_labels))
        self.connect("clicked", lambda _button: action(result))


class ScreenshotGallery(Gtk.Box):
    def __init__(self, urls, language):
        from sourcedock.i18n import t
        import threading

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._closed = False
        self.language = language
        self.status = Gtk.Label(label=t(language, "store_screenshots_loading"), xalign=0)
        self.status.get_style_context().add_class("dim-label")
        self.pack_start(self.status, False, False, 0)
        self.images = Gtk.Box(spacing=12)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_min_content_height(180)
        scroller.add(self.images)
        self.pack_start(scroller, False, False, 0)
        self.connect("destroy", lambda _widget: setattr(self, "_closed", True))
        threading.Thread(target=self._load, args=(urls,), daemon=True).start()

    def _load(self, urls):
        import urllib.request

        pixbufs = []
        for url in urls[:4]:
            if self._closed or not url.startswith("https://"):
                break
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "SourceDock"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = response.read(5 * 1024 * 1024 + 1)
                if len(data) > 5 * 1024 * 1024:
                    continue
                loader = GdkPixbuf.PixbufLoader.new()

                def resize(image_loader, width, height):
                    factor = min(320 / max(1, width), 180 / max(1, height))
                    image_loader.set_size(max(1, int(width * factor)), max(1, int(height * factor)))

                loader.connect("size-prepared", resize)
                loader.write(data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    pixbufs.append(pixbuf)
            except Exception:
                continue
        GLib.idle_add(self._finish, pixbufs)

    def _finish(self, pixbufs):
        from sourcedock.i18n import t

        if self._closed:
            return False
        self.status.set_text("" if pixbufs else t(self.language, "store_screenshots_none"))
        for pixbuf in pixbufs:
            self.images.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
        self.images.show_all()
        return False
