"""Small native widgets shared across the application screens."""

import gi
import threading

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango


def icon_button(button, icon_name: str, tooltip: str) -> None:
    button.set_label("")
    button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    button.set_always_show_image(True)
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    button.get_style_context().add_class("icon-button")


def icon_text_button(button, icon_name: str, label: str, tooltip: str) -> None:
    """Use a labelled action when the icon alone would be ambiguous."""
    button.set_label(label)
    button.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))
    button.set_always_show_image(True)
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(label)


def prepare_dialog(
    dialog: Gtk.Dialog,
    width: int = 520,
    height: int = 360,
    *,
    independent: bool = False,
) -> None:
    """Apply shared sizing rules, optionally turning a dialog into a tool window."""
    dialog.set_default_size(width, height)
    dialog.set_resizable(True)
    make_window_movable(dialog, independent=independent)
    dialog.get_style_context().add_class("icon-settings-window")


def make_window_movable(window: Gtk.Window, *, independent: bool = False) -> None:
    """Keep small windows draggable and optionally detach them from their parent."""
    if getattr(window, "_sourcedock_move_handler", False):
        if independent:
            _detach_independent_window(window)
        return
    window._sourcedock_move_handler = True
    window.set_resizable(True)
    window.set_decorated(True)
    if independent:
        _detach_independent_window(window)

    def begin_drag(_window: Gtk.Window, event: Gdk.EventButton) -> bool:
        # The narrow upper surface is an explicit drag affordance while the
        # actual titlebar is owned by the desktop window manager. Content
        # controls below it keep their normal click behavior.
        if event.button != 1 or event.y > 48:
            return False
        try:
            window.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
            return True
        except (AttributeError, TypeError):
            return False

    window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    window.connect("button-press-event", begin_drag)


def _detach_independent_window(window: Gtk.Window) -> None:
    """Make an informational/tool window a normal desktop window.

    Modal confirmations intentionally do not use this helper. Keeping the
    policy here avoids accidentally weakening password or risk prompts while
    allowing long-lived detail and progress windows to be moved independently.
    """
    window.set_modal(False)
    window.set_transient_for(None)
    window.set_destroy_with_parent(False)
    window.set_type_hint(Gdk.WindowTypeHint.NORMAL)
    window.set_skip_taskbar_hint(False)
    window.set_skip_pager_hint(False)
    window.set_position(Gtk.WindowPosition.CENTER)


def load_dialog_data(parent, title, worker, show_result):
    """Load read-only dialog data without blocking GTK or reopening a cancelled dialog."""
    from sourcedock.i18n import t

    loading = Gtk.Dialog(title=title, transient_for=parent, modal=True, destroy_with_parent=True)
    prepare_dialog(loading, width=420, height=160)
    loading.add_button(t(parent.preferences.language, "password_cancel"), Gtk.ResponseType.CANCEL)
    loading._closed = False
    loading.connect("destroy", lambda widget: setattr(widget, "_closed", True))
    loading.connect("response", lambda widget, _response: widget.destroy())
    spinner = Gtk.Spinner()
    spinner.start()
    spinner.get_accessible().set_name(title)
    loading.get_content_area().pack_start(spinner, True, True, 16)
    loading.show_all()

    def finish(result, error):
        if loading._closed:
            return False
        loading.destroy()
        if error is not None:
            parent._show_error_dialog(str(error))
        else:
            show_result(result)
        return False

    def run():
        try:
            result = worker()
        except Exception as exc:
            GLib.idle_add(finish, None, exc)
        else:
            GLib.idle_add(finish, result, None)

    threading.Thread(target=run, daemon=True).start()
    return loading


def display_store_name(result) -> str:
    """Humanize a bare package ID while preserving provider-supplied names."""
    import re

    name = (result.name or result.app_id or "").strip()
    if name == result.app_id and name.islower() and re.fullmatch(r"[a-z0-9][a-z0-9+_.-]*", name):
        return name.replace("-", " ").replace("_", " ").title()
    return name


def set_status(label, message: str, error: bool = False) -> None:
    label.set_text(message)
    context = label.get_style_context()
    context.remove_class("error-text")
    context.remove_class("dim-label")
    context.add_class("error-text" if error else "dim-label")


def style_tree_view(tree: Gtk.TreeView) -> None:
    """Keep dense tables easy to scan without bright native grid lines."""
    tree.set_grid_lines(Gtk.TreeViewGridLines.NONE)
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
        self.retry_button = Gtk.Button()
        self.retry_button.get_style_context().add_class("secondary-action")
        self.retry_button.hide()
        panel.pack_start(self.retry_button, False, False, 0)
        self._retry_handler_id = None
        self.add_named(panel, "state")
        self.show_all()
        self.retry_button.hide()
        self.show_content()

    def show_content(self):
        self.spinner.stop()
        if self.get_child_by_name("content") is not None:
            self.set_visible_child_name("content")

    def show_state(
        self,
        title: str,
        body: str = "",
        loading: bool = False,
        error: bool = False,
        retry_callback=None,
        retry_label: str = "Retry",
        icon_name: str | None = None,
    ):
        if self._retry_handler_id is not None:
            self.retry_button.disconnect(self._retry_handler_id)
            self._retry_handler_id = None
        self.title.set_text(title)
        self.body.set_text(body)
        self.icon.set_from_icon_name(
            icon_name or ("dialog-warning-symbolic" if error else "system-search-symbolic"),
            Gtk.IconSize.DIALOG,
        )
        self.icon.set_visible(not loading)
        self.spinner.set_visible(loading)
        self.spinner.start() if loading else self.spinner.stop()
        self.retry_button.set_visible(bool(retry_callback) and not loading)
        if retry_callback:
            self.retry_button.set_label(retry_label)
            self._retry_handler_id = self.retry_button.connect("clicked", lambda *_args: retry_callback())
        if self.get_child_by_name("state") is not None:
            self.set_visible_child_name("state")


class AppCard(Gtk.Button):
    def __init__(self, result, pixbuf, installed, action, language, variants=(), source_states=None):
        from sourcedock.i18n import source_name, t

        super().__init__()
        self.get_style_context().add_class("app-card")
        self.set_size_request(250, 176)
        self.set_hexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(spacing=10)
        image = (
            Gtk.Image.new_from_pixbuf(pixbuf)
            if pixbuf
            else Gtk.Image.new_from_icon_name("package-x-generic", Gtk.IconSize.DIALOG)
        )
        image.set_pixel_size(48)
        header.pack_start(image, False, False, 0)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name = Gtk.Label(label=display_store_name(result), xalign=0)
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

        source_states = source_states or {}
        source_names = [result.source]
        source_names.extend(variant.source for variant in variants if variant.source not in source_names)
        source_labels = []
        for source in source_names:
            label = source_name(language, source)
            if source_states.get(source) == "cached":
                label = f"{label} · {t(language, 'store_source_cached_short')}"
            elif source_states.get(source) == "unavailable":
                label = f"{label} · {t(language, 'store_source_unavailable_short')}"
            source_labels.append(label)
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
        self.get_accessible().set_name(display_store_name(result) + ", " + ", ".join(source_labels))
        self.connect("clicked", lambda _button: action(result))


class ScreenshotGallery(Gtk.Box):
    def __init__(self, urls, language):
        from sourcedock.i18n import t
        import threading

        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._closed = False
        self._finished = False
        self._timeout_id = GLib.timeout_add_seconds(12, self._on_timeout)
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
        self.set_no_show_all(True)
        self.hide()
        self.connect("destroy", self._on_destroy)
        threading.Thread(target=self._load, args=(urls,), daemon=True).start()

    def _on_destroy(self, _widget) -> None:
        self._closed = True
        if self._timeout_id:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = 0

    def _on_timeout(self) -> bool:
        if self._closed or self._finished:
            return False
        from sourcedock.i18n import t

        self._finished = True
        self.hide()
        return False

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

        if self._closed or self._finished:
            return False
        self._finished = True
        if self._timeout_id:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = 0
        if not pixbufs:
            self.hide()
            return False
        self.status.hide()
        for pixbuf in pixbufs:
            self.images.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
        self.images.show_all()
        self.show()
        return False
