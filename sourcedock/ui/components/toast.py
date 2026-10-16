"""Toast and snackbar notification components for transient feedback.

Toasts are non-blocking, announced to assistive technology and never steal
keyboard focus. They are used for short confirmations (a copy, an export) so the
interface does not need a modal dialog for every successful action.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # pyright: ignore[reportMissingModuleSource]

from sourcedock.i18n import t


class ToastNotification(Gtk.Box):
    """Floating transient notification bar."""

    def __init__(
        self,
        message: str,
        level: str = "info",
        on_close: Callable[[], None] | None = None,
        language: str = "tr",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.on_close = on_close
        self.get_style_context().add_class("toast-box")
        self.get_style_context().add_class(f"toast-{level}")

        icon_names = {
            "success": "emblem-default-symbolic",
            "warning": "dialog-warning-symbolic",
            "danger": "dialog-error-symbolic",
            "error": "dialog-error-symbolic",
            "info": "dialog-information-symbolic",
        }
        icon_name = icon_names.get(level, "dialog-information-symbolic")
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        icon.get_style_context().add_class(f"toast-icon-{level}")
        self.pack_start(icon, False, False, 0)

        label = Gtk.Label(label=message)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_max_width_chars(60)
        label.get_style_context().add_class("toast-label")
        self.pack_start(label, True, True, 0)

        close_btn = Gtk.Button()
        close_btn.set_image(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON))
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.get_style_context().add_class("toast-close-btn")
        close_btn.set_tooltip_text(t(language, "toast_close"))
        close_btn.get_accessible().set_name(t(language, "toast_close"))
        close_btn.connect("clicked", self._on_close_clicked)
        self.pack_end(close_btn, False, False, 0)

        self.get_accessible().set_name(f"{level}: {message}")

    def _on_close_clicked(self) -> None:
        if self.on_close:
            self.on_close()


class ToastHost(Gtk.Overlay):
    """Overlay that floats auto-dismissing toasts above the window content."""

    def __init__(self, child: Gtk.Widget, language: str = "tr") -> None:
        super().__init__()
        self.language = language
        self.add(child)
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._revealer.set_halign(Gtk.Align.CENTER)
        self._revealer.set_valign(Gtk.Align.END)
        self._revealer.set_margin_bottom(16)
        self._revealer.set_margin_start(16)
        self._revealer.set_margin_end(16)
        self._current: ToastNotification | None = None
        self._timeout_id = 0
        self.add_overlay(self._revealer)

    def show_toast(self, message: str, level: str = "info", timeout: int = 4) -> ToastNotification:
        """Display ``message``; a non-positive ``timeout`` keeps it until dismissed."""
        self._cancel_timeout()
        if self._current is not None:
            self._revealer.remove(self._current)
            self._current.destroy()
        toast = ToastNotification(
            message, level=level, on_close=self.hide_toast, language=self.language
        )
        self._current = toast
        self._revealer.add(toast)
        self._revealer.show_all()
        self._revealer.set_reveal_child(True)
        if timeout > 0:
            self._timeout_id = GLib.timeout_add_seconds(timeout, self._on_timeout)
        return toast

    def hide_toast(self) -> None:
        self._cancel_timeout()
        self._revealer.set_reveal_child(False)

    def _cancel_timeout(self) -> None:
        if self._timeout_id:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = 0

    def _on_timeout(self) -> bool:
        self._timeout_id = 0
        self._revealer.set_reveal_child(False)
        return False
