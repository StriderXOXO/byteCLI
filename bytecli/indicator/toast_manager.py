"""
ToastManager -- floating toast notification system for the indicator.

Creates small notification windows at the bottom-right corner of the
screen that stack upward and auto-dismiss after 2 seconds.  Four visual
variants are supported: success, error, warning, info.

Design tokens
-------------
- Card background ``#1A1A1A``, border ``1px #2E2E2E``, border-radius 8px.
- Left colour bar 3px wide: success=#B6FFCE, error=#FF5C33, warning=#FF8400,
  info=#B2B2FF.
- Icon 16px, message text white.
- Toast width 320px, positioned 24px from bottom-right screen edge.
- Multiple toasts stack vertically with 8px gap.
- Auto-dismiss after 2 seconds via ``GLib.timeout_add``.
- Singleton access: ``ToastManager.instance()``.
"""

from __future__ import annotations

import logging
import math
import subprocess
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

logger = logging.getLogger(__name__)

_TOAST_WIDTH = 320
_EDGE_MARGIN = 24
_TOAST_SPACING = 8
_AUTO_DISMISS_MS = 2000

# Variant configuration: (bar_color_rgba, icon_name, icon_color_hex)
_VARIANTS = {
    "success": ((0.714, 1.0, 0.808, 1.0), "emblem-ok-symbolic", "#B6FFCE"),
    "error": ((1.0, 0.36, 0.2, 1.0), "dialog-error-symbolic", "#FF5C33"),
    "warning": ((1.0, 0.518, 0.0, 1.0), "dialog-warning-symbolic", "#FF8400"),
    "info": ((0.698, 0.698, 1.0, 1.0), "dialog-information-symbolic", "#B2B2FF"),
}

# Inline CSS applied to every toast window for the card appearance.
_TOAST_CSS = b"""
.toast {
    background-color: #1A1A1A;
    border: 1px solid #2E2E2E;
    border-radius: 8px;
    padding: 10px 14px;
    color: #FFFFFF;
}
"""


class _ToastWindow(Gtk.Window):
    """A single toast notification window."""

    def __init__(self, variant: str, message: str) -> None:
        super().__init__()
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_can_focus(False)
        self.set_focusable(False)
        self.set_default_size(_TOAST_WIDTH, -1)
        self.set_title("ByteCLI Toast")

        bar_rgba, icon_name, icon_color = _VARIANTS.get(
            variant, _VARIANTS["info"]
        )

        # Apply card CSS to this window.
        card_provider = Gtk.CssProvider()
        card_provider.load_from_data(_TOAST_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            card_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Root container.
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        root.add_css_class("toast")
        root.add_css_class(f"toast-{variant}")
        root.set_margin_start(0)
        root.set_margin_end(0)

        # Colour bar (3px wide, 20px tall, rounded).
        bar = Gtk.DrawingArea()
        bar.set_size_request(3, 20)
        bar.set_valign(Gtk.Align.CENTER)
        bar.set_draw_func(self._make_bar_draw(bar_rgba))
        root.append(bar)

        # Icon.
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        icon.set_valign(Gtk.Align.CENTER)
        # Apply icon colour via CSS.
        icon_provider = Gtk.CssProvider()
        icon_provider.load_from_data(f"* {{ color: {icon_color}; }}".encode())
        icon.get_style_context().add_provider(
            icon_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        root.append(icon)

        # Message label.
        label = Gtk.Label(label=message)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_wrap(True)
        label.set_max_width_chars(38)
        _apply_font_size(label, 13)
        root.append(label)

        self.set_child(root)

        # Apply X11 properties after realize.
        self.connect("realize", self._on_realize)

    @staticmethod
    def _make_bar_draw(rgba):
        def _draw(area, cr, w, h):
            cr.set_source_rgba(*rgba)
            _rounded_rect(cr, 0, 0, w, h, 2)
            cr.fill()
        return _draw

    def _on_realize(self, widget) -> None:
        GLib.idle_add(self._apply_x11)

    def _apply_x11(self) -> bool:
        """Set ``_NET_WM_STATE_ABOVE`` via ``xprop`` so the toast floats."""
        surface = self.get_surface()
        if surface is None:
            return False
        try:
            from gi.repository import GdkX11

            if not isinstance(surface, GdkX11.X11Surface):
                return False
            xid = surface.get_xid()
        except (ImportError, AttributeError):
            return False

        try:
            subprocess.Popen(
                [
                    "xprop", "-id", str(xid),
                    "-f", "_NET_WM_WINDOW_TYPE", "32a",
                    "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_NOTIFICATION",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                [
                    "xprop", "-id", str(xid),
                    "-f", "_NET_WM_STATE", "32a",
                    "-set", "_NET_WM_STATE", "_NET_WM_STATE_ABOVE",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass
        return False


class ToastManager:
    """Singleton manager that owns the toast stack.

    Access via ``ToastManager.instance()``.
    """

    _instance: Optional["ToastManager"] = None

    def __init__(self) -> None:
        self._toasts: list[_ToastWindow] = []

    @classmethod
    def instance(cls) -> "ToastManager":
        """Return the singleton ``ToastManager``, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_toast(self, variant: str, message: str) -> None:
        """Create and display a toast notification.

        Parameters
        ----------
        variant:
            One of ``"success"``, ``"error"``, ``"warning"``, ``"info"``.
        message:
            Text to display inside the toast.
        """
        toast = _ToastWindow(variant, message)
        self._toasts.append(toast)
        toast.connect("realize", lambda w: GLib.idle_add(self._position_toasts))
        toast.present()

        # Schedule auto-dismiss after 2 seconds.
        GLib.timeout_add(_AUTO_DISMISS_MS, self._dismiss, toast)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _dismiss(self, toast: _ToastWindow) -> bool:
        """Remove and destroy *toast* from the stack."""
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.set_visible(False)
            toast.destroy()
            self._position_toasts()
        return False

    def _position_toasts(self) -> bool:
        """Reposition all visible toasts stacking from bottom-right."""
        display = Gdk.Display.get_default()
        if display is None:
            return False
        monitors = display.get_monitors()
        if monitors.get_n_items() == 0:
            return False

        monitor = monitors.get_item(0)
        geo = monitor.get_geometry()

        # Stack from bottom-right, newest at the bottom of the visual stack.
        y_cursor = geo.y + geo.height - _EDGE_MARGIN
        x = geo.x + geo.width - _TOAST_WIDTH - _EDGE_MARGIN

        for toast in reversed(self._toasts):
            nat_h = toast.get_preferred_size()[1].height
            if nat_h <= 0:
                nat_h = 56
            y_cursor -= nat_h
            surface = toast.get_surface()
            if surface is not None:
                try:
                    from gi.repository import GdkX11

                    if isinstance(surface, GdkX11.X11Surface):
                        surface.move(x, y_cursor)
                except (ImportError, AttributeError):
                    pass
            y_cursor -= _TOAST_SPACING

        return False


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _rounded_rect(cr, x, y, w, h, r):
    """Draw a rounded rectangle path."""
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _apply_font_size(widget: Gtk.Widget, size_px: int) -> None:
    provider = Gtk.CssProvider()
    css = f"* {{ font-size: {size_px}px; }}"
    provider.load_from_data(css.encode())
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
