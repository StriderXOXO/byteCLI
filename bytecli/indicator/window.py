"""
IndicatorWindow -- floating pill-shaped status indicator.

Sits at the bottom-center of the primary monitor displaying the current
dictation state (idle / recording) with an elapsed-time counter.  On
hover the widget expands to reveal a History button that opens the
HistoryPanel popup.
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

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient

logger = logging.getLogger(__name__)

# Margin from the bottom edge of the screen.
_BOTTOM_MARGIN = 48


class IndicatorWindow(Gtk.Window):
    """Undecorated pill window pinned to the bottom-center of the screen."""

    def __init__(
        self,
        application: Gtk.Application,
        dbus_client: DBusClient,
    ) -> None:
        super().__init__(application=application)
        self._dbus_client = dbus_client
        self._recording = False
        self._timer_seconds = 0
        self._timer_source_id: Optional[int] = None
        self._leave_timeout_id: Optional[int] = None
        self._history_panel = None

        # Window chrome.
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_can_focus(False)
        self.set_focusable(False)
        self.set_title("ByteCLI Indicator")

        # Build UI.
        self._build_ui()

        # Position after the window is realized so we can read monitor geometry.
        self.connect("realize", self._on_realize)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Root box with the pill CSS class.
        self._pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._pill_box.add_css_class("indicator-pill")
        self._pill_box.set_margin_start(0)
        self._pill_box.set_margin_end(0)

        # --- Status dot (8x8 DrawingArea) --------------------------------
        self._dot = Gtk.DrawingArea()
        self._dot.set_size_request(8, 8)
        self._dot.set_valign(Gtk.Align.CENTER)
        self._dot.set_draw_func(self._draw_dot)
        self._pill_box.append(self._dot)

        # --- Status text -------------------------------------------------
        self._status_label = Gtk.Label(label=i18n.t("indicator.idle", fallback="Idle"))
        self._status_label.add_css_class("mono")
        self._status_label.add_css_class("font-medium")
        self._status_label.set_valign(Gtk.Align.CENTER)
        # 13px via inline style
        _apply_font_size(self._status_label, 13)
        self._pill_box.append(self._status_label)

        # --- Timer label (visible only while recording) ------------------
        self._timer_label = Gtk.Label(label="00:00")
        self._timer_label.add_css_class("mono")
        self._timer_label.add_css_class("text-muted")
        self._timer_label.set_valign(Gtk.Align.CENTER)
        _apply_font_size(self._timer_label, 13)
        self._timer_label.set_visible(False)
        self._pill_box.append(self._timer_label)

        # --- Separator (visible on hover) --------------------------------
        self._separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self._separator.set_size_request(1, 16)
        self._separator.set_valign(Gtk.Align.CENTER)
        self._separator.set_visible(False)
        self._pill_box.append(self._separator)

        # --- History button (visible on hover) ---------------------------
        self._history_btn = Gtk.Button()
        self._history_btn.add_css_class("icon-btn")
        history_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        history_box.set_valign(Gtk.Align.CENTER)

        history_icon = Gtk.Image.new_from_icon_name("document-open-recent-symbolic")
        history_icon.set_pixel_size(14)
        history_box.append(history_icon)

        history_text = Gtk.Label(label=i18n.t("indicator.history", fallback="History"))
        history_text.add_css_class("text-sm")
        history_box.append(history_text)

        self._history_btn.set_child(history_box)
        self._history_btn.set_visible(False)
        self._history_btn.connect("clicked", self._on_history_clicked)
        self._pill_box.append(self._history_btn)

        # --- Hover detection ---------------------------------------------
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_mouse_enter)
        motion.connect("leave", self._on_mouse_leave)
        self._pill_box.add_controller(motion)

        self.set_child(self._pill_box)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_dot(
        self,
        area: Gtk.DrawingArea,
        cr,
        width: int,
        height: int,
    ) -> None:
        """Draw a filled circle as the status dot."""
        if self._recording:
            cr.set_source_rgba(0.714, 1.0, 0.808, 1.0)  # #B6FFCE
        else:
            cr.set_source_rgba(0.722, 0.725, 0.714, 1.0)  # #B8B9B6
        radius = min(width, height) / 2.0
        cr.arc(width / 2.0, height / 2.0, radius, 0, 2 * math.pi)
        cr.fill()

    # ------------------------------------------------------------------
    # Positioning & X11 properties
    # ------------------------------------------------------------------

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Set X11 window type to DOCK + ABOVE + STICKY and position the pill."""
        GLib.idle_add(self._apply_x11_properties)
        GLib.idle_add(self._position_on_screen)

    def _apply_x11_properties(self) -> bool:
        """Use xprop to set the window type and state via the X11 window id."""
        surface = self.get_surface()
        if surface is None:
            return False

        try:
            from gi.repository import GdkX11  # noqa: F401 -- ensure X11 backend

            if not isinstance(surface, GdkX11.X11Surface):
                logger.warning("Not running on X11; skipping xprop calls.")
                return False

            xid = surface.get_xid()
        except (ImportError, AttributeError):
            logger.warning("GdkX11 not available; skipping xprop calls.")
            return False

        try:
            subprocess.Popen(
                [
                    "xprop",
                    "-id", str(xid),
                    "-f", "_NET_WM_WINDOW_TYPE", "32a",
                    "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                [
                    "xprop",
                    "-id", str(xid),
                    "-f", "_NET_WM_STATE", "32a",
                    "-set", "_NET_WM_STATE",
                    "_NET_WM_STATE_ABOVE,_NET_WM_STATE_STICKY",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.warning("xprop not found; indicator may not stay above other windows.")

        return False  # do not repeat

    def _position_on_screen(self) -> bool:
        """Center the window at the bottom of the primary monitor."""
        display = Gdk.Display.get_default()
        if display is None:
            return False

        monitors = display.get_monitors()
        if monitors.get_n_items() == 0:
            return False

        monitor = monitors.get_item(0)
        geo = monitor.get_geometry()

        # The natural size of the pill.
        nat_width = self.get_preferred_size()[1].width
        if nat_width <= 0:
            nat_width = 220  # fallback

        x = geo.x + (geo.width - nat_width) // 2
        y = geo.y + geo.height - _BOTTOM_MARGIN - 40  # 40px approx pill height

        surface = self.get_surface()
        if surface is not None:
            try:
                from gi.repository import GdkX11

                if isinstance(surface, GdkX11.X11Surface):
                    surface.move(x, y)
            except (ImportError, AttributeError):
                pass

        return False  # do not repeat

    # ------------------------------------------------------------------
    # Hover logic
    # ------------------------------------------------------------------

    def _on_mouse_enter(self, controller, x, y) -> None:
        if self._leave_timeout_id is not None:
            GLib.source_remove(self._leave_timeout_id)
            self._leave_timeout_id = None
        self._separator.set_visible(True)
        self._history_btn.set_visible(True)

    def _on_mouse_leave(self, controller) -> None:
        # Delay hiding so the user can reach the history button / panel.
        self._leave_timeout_id = GLib.timeout_add(400, self._hide_hover_widgets)

    def _hide_hover_widgets(self) -> bool:
        """Hide separator and history button after mouse leaves."""
        # If the history panel is open, keep them visible.
        if self._history_panel is not None and self._history_panel.get_visible():
            return False
        self._separator.set_visible(False)
        self._history_btn.set_visible(False)
        self._leave_timeout_id = None
        return False  # do not repeat

    # ------------------------------------------------------------------
    # History panel
    # ------------------------------------------------------------------

    def _on_history_clicked(self, button: Gtk.Button) -> None:
        from bytecli.indicator.history_panel import HistoryPanel

        if self._history_panel is not None:
            self._history_panel.set_visible(not self._history_panel.get_visible())
            if self._history_panel.get_visible():
                self._history_panel.refresh()
            return

        self._history_panel = HistoryPanel(
            parent_window=self,
            dbus_client=self._dbus_client,
        )
        self._history_panel.connect("hide", self._on_history_hidden)
        self._history_panel.present()

    def _on_history_hidden(self, widget) -> None:
        # Trigger the leave-hide logic after the panel closes.
        self._leave_timeout_id = GLib.timeout_add(200, self._hide_hover_widgets)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def set_state_idle(self) -> None:
        self._recording = False
        self._stop_timer()
        self._status_label.set_text(i18n.t("indicator.idle", fallback="Idle"))
        self._timer_label.set_visible(False)
        self._dot.queue_draw()

    def set_state_recording(self) -> None:
        self._recording = True
        self._timer_seconds = 0
        self._timer_label.set_text("00:00")
        self._timer_label.set_visible(True)
        self._status_label.set_text(i18n.t("indicator.recording", fallback="Recording"))
        self._dot.queue_draw()
        self._start_timer()

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        self._stop_timer()
        self._timer_source_id = GLib.timeout_add(1000, self._tick)

    def _stop_timer(self) -> None:
        if self._timer_source_id is not None:
            GLib.source_remove(self._timer_source_id)
            self._timer_source_id = None

    def _tick(self) -> bool:
        self._timer_seconds += 1
        mins, secs = divmod(self._timer_seconds, 60)
        self._timer_label.set_text(f"{mins:02d}:{secs:02d}")
        return True  # keep ticking


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _apply_font_size(widget: Gtk.Widget, size_px: int) -> None:
    """Apply a pixel font size via an inline CSS provider."""
    provider = Gtk.CssProvider()
    css = f"* {{ font-size: {size_px}px; }}"
    provider.load_from_data(css.encode())
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
