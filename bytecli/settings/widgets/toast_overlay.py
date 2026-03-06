"""
SettingsToastOverlay -- in-window toast notification manager.

Shows toast messages at the bottom of the settings window with
auto-dismiss after 3 seconds.

Variants:
    success -- green accent bar
    error   -- red accent bar
    warning -- orange accent bar
    info    -- blue accent bar

Usage::

    overlay = SettingsToastOverlay(gtk_overlay)
    overlay.show_toast("Settings saved successfully", variant="success")
"""

from __future__ import annotations

import math
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

_AUTO_DISMISS_MS = 3000

_VARIANT_CONFIG = {
    "success": ("#B6FFCE", "emblem-ok-symbolic"),
    "error": ("#FF5C33", "dialog-error-symbolic"),
    "warning": ("#FF8400", "dialog-warning-symbolic"),
    "info": ("#B2B2FF", "dialog-information-symbolic"),
}


class SettingsToastOverlay:
    """Manages toast display inside a Gtk.Overlay.

    Parameters
    ----------
    overlay:
        The ``Gtk.Overlay`` that will contain the floating toasts.
    """

    def __init__(self, overlay: Gtk.Overlay) -> None:
        self._overlay = overlay
        self._active_toasts: list[Gtk.Box] = []

    def show_toast(self, message: str, variant: str = "info") -> None:
        """Create and display a toast notification.

        Parameters
        ----------
        message:
            Text content of the toast.
        variant:
            ``"success"``, ``"error"``, ``"warning"`` or ``"info"``.
        """
        color, icon_name = _VARIANT_CONFIG.get(variant, _VARIANT_CONFIG["info"])

        # Toast container.
        toast = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toast.get_style_context().add_class("toast")
        toast.get_style_context().add_class(f"toast-{variant}")
        toast.set_halign(Gtk.Align.CENTER)
        toast.set_valign(Gtk.Align.END)
        toast.set_margin_bottom(16)
        toast.set_size_request(300, -1)

        # Colour accent bar.
        bar = Gtk.DrawingArea()
        bar.set_size_request(3, 20)
        bar.set_valign(Gtk.Align.CENTER)
        bar.connect("draw", self._make_bar_draw(color))
        toast.pack_start(bar, False, False, 0)

        # Icon.
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        icon.set_pixel_size(16)
        icon.set_valign(Gtk.Align.CENTER)
        provider = Gtk.CssProvider()
        provider.load_from_data(f"* {{ color: {color}; }}".encode())
        icon.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        toast.pack_start(icon, False, False, 0)

        # Message label.
        label = Gtk.Label(label=message)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        _apply_font_size(label, 13)
        toast.pack_start(label, True, True, 0)

        self._overlay.add_overlay(toast)
        toast.show_all()
        self._active_toasts.append(toast)

        # Auto-dismiss after 3 seconds.
        GLib.timeout_add(_AUTO_DISMISS_MS, self._dismiss, toast)

    def _dismiss(self, toast: Gtk.Box) -> bool:
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)
            self._overlay.remove(toast)
        return False

    @staticmethod
    def _make_bar_draw(hex_color: str):
        r, g, b = _hex_to_rgb(hex_color)

        def _draw(area, cr):
            w = area.get_allocated_width()
            h = area.get_allocated_height()
            cr.set_source_rgba(r, g, b, 1.0)
            _rounded_rect(cr, 0, 0, w, h, 2)
            cr.fill()

        return _draw


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    hex_str = hex_str.lstrip("#")
    return (
        int(hex_str[0:2], 16) / 255.0,
        int(hex_str[2:4], 16) / 255.0,
        int(hex_str[4:6], 16) / 255.0,
    )


def _rounded_rect(cr, x, y, w, h, r):
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
