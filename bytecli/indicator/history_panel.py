"""
HistoryPanel -- popup window showing recent voice-input transcriptions.

Positioned directly above the indicator pill.  Fetches entries from the
ByteCLI service via D-Bus ``GetHistory()`` and lets the user copy any
entry to the clipboard with a single click.

Visibility is managed by polling the global pointer position (via
``xdotool getmouselocation``) rather than GTK4 EventControllerMotion,
because motion events are not reliably delivered to non-focusable
popup windows.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient

logger = logging.getLogger(__name__)

_PANEL_WIDTH = 300
_MAX_ENTRIES = 20
_EMPTY_HEIGHT = 120

# Polling interval in milliseconds.
_POLL_INTERVAL_MS = 200
# How many consecutive "outside" polls before hiding (3 × 200 ms = 600 ms).
_MISS_THRESHOLD = 3


class HistoryPanel(Gtk.Window):
    """Popup window listing recent transcription entries."""

    def __init__(
        self,
        parent_window: Gtk.Window,
        dbus_client: DBusClient,
    ) -> None:
        super().__init__()
        self._parent_window = parent_window
        self._dbus_client = dbus_client

        # Pointer polling state.
        self._poll_source_id: Optional[int] = None
        self._miss_count = 0

        # Window setup.
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(_PANEL_WIDTH, -1)
        self.set_can_focus(False)
        self.set_title("ByteCLI History")

        # Build the UI shell.
        self._outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._outer_box.add_css_class("history-panel")
        self._outer_box.set_size_request(_PANEL_WIDTH, -1)

        # Inline CSS for the panel background.
        self._apply_panel_css()

        # Header row.
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_margin_start(14)
        header.set_margin_end(14)
        header.set_margin_top(10)
        header.set_margin_bottom(10)

        title_label = Gtk.Label(label=i18n.t("indicator.history", fallback="History"))
        title_label.add_css_class("font-semibold")
        title_label.set_halign(Gtk.Align.START)
        _apply_font_size(title_label, 13)
        header.append(title_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        self._count_label = Gtk.Label(label="")
        self._count_label.add_css_class("text-muted")
        _apply_font_size(self._count_label, 11)
        self._count_label.set_halign(Gtk.Align.END)
        header.append(self._count_label)

        self._outer_box.append(header)

        # Separator.
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._outer_box.append(sep)

        # Scrolled area for entries.
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(400)
        self._scroll.set_propagate_natural_height(True)

        self._entries_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._scroll.set_child(self._entries_box)
        self._outer_box.append(self._scroll)

        self.set_child(self._outer_box)

        # Position after realize.
        self.connect("realize", self._on_realize)

        # Start/stop polling when visibility changes.
        self.connect("notify::visible", self._on_visibility_changed)

        # Load entries.
        self.refresh()

    # ------------------------------------------------------------------
    # Positioning & X11
    # ------------------------------------------------------------------

    def _on_realize(self, widget: Gtk.Widget) -> None:
        GLib.idle_add(self._apply_x11_properties)
        GLib.idle_add(self._position_above_indicator)

    def _apply_x11_properties(self) -> bool:
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
                    "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_POPUP_MENU",
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

    def _position_above_indicator(self) -> bool:
        """Place the panel above the indicator pill, centered horizontally."""
        display = Gdk.Display.get_default()
        if display is None:
            return False
        monitors = display.get_monitors()
        if monitors.get_n_items() == 0:
            return False

        monitor = monitors.get_item(0)
        geo = monitor.get_geometry()

        nat_height = self.get_preferred_size()[1].height
        if nat_height <= 0:
            nat_height = 300

        x = geo.x + (geo.width - _PANEL_WIDTH) // 2
        # Indicator is 48px from bottom + ~40px tall. Panel goes above that.
        y = geo.y + geo.height - 48 - 40 - nat_height - 2

        surface = self.get_surface()
        if surface is not None:
            try:
                from gi.repository import GdkX11

                if isinstance(surface, GdkX11.X11Surface):
                    surface.move(x, y)
            except (ImportError, AttributeError):
                pass
        return False

    # ------------------------------------------------------------------
    # Pointer polling (replaces EventControllerMotion)
    # ------------------------------------------------------------------

    def _on_visibility_changed(self, widget, pspec) -> None:
        if self.get_visible():
            self._start_hover_poll()
        else:
            self._stop_hover_poll()

    def _start_hover_poll(self) -> None:
        self._miss_count = 0
        if self._poll_source_id is None:
            self._poll_source_id = GLib.timeout_add(
                _POLL_INTERVAL_MS, self._check_pointer
            )

    def _stop_hover_poll(self) -> None:
        if self._poll_source_id is not None:
            GLib.source_remove(self._poll_source_id)
            self._poll_source_id = None

    def _check_pointer(self) -> bool:
        """Poll the pointer; hide if not over the panel or indicator window."""
        try:
            result = subprocess.run(
                ["xdotool", "getmouselocation", "--shell"],
                capture_output=True, text=True, timeout=1,
            )
            if result.returncode != 0:
                return True  # keep polling

            window_id = 0
            for line in result.stdout.splitlines():
                if line.startswith("WINDOW="):
                    window_id = int(line[7:])
                    break

        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            return True  # keep polling on error

        if window_id in self._get_our_xids():
            self._miss_count = 0
        else:
            self._miss_count += 1
            if self._miss_count >= _MISS_THRESHOLD:
                self.set_visible(False)
                self._poll_source_id = None
                return False  # stop polling

        return True  # keep polling

    def _get_our_xids(self) -> set[int]:
        """Return the X11 window IDs of the panel and the indicator."""
        xids: set[int] = set()
        # Panel XID.
        surface = self.get_surface()
        if surface is not None:
            try:
                from gi.repository import GdkX11
                if isinstance(surface, GdkX11.X11Surface):
                    xids.add(surface.get_xid())
            except (ImportError, AttributeError):
                pass
        # Indicator XID.
        indicator_xid = self._parent_window.get_xid()
        if indicator_xid:
            xids.add(indicator_xid)
        return xids

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Fetch history from D-Bus and rebuild the entry list."""
        # Clear existing children.
        child = self._entries_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._entries_box.remove(child)
            child = next_child

        entries = self._dbus_client.get_history()
        if entries is None:
            entries = []

        entries = entries[:_MAX_ENTRIES]

        if not entries:
            self._show_empty_state()
            self._count_label.set_text("")
            return

        count = len(entries)
        self._count_label.set_text(
            i18n.t("indicator.history_count", n=count, fallback=f"{count} entries")
        )

        for idx, entry in enumerate(entries):
            # D-Bus returns (text, timestamp, id) tuples.
            if isinstance(entry, (tuple, list)) and len(entry) >= 1:
                text = str(entry[0])
                timestamp = str(entry[1]) if len(entry) >= 2 else ""
            elif isinstance(entry, dict):
                text = entry.get("text", str(entry))
                timestamp = entry.get("timestamp", "")
            else:
                text = str(entry)
                timestamp = ""
            row = self._build_entry_row(text, timestamp)
            self._entries_box.append(row)

            # Separator between rows (not after the last one).
            if idx < count - 1:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                self._entries_box.append(sep)

    # ------------------------------------------------------------------
    # Row construction
    # ------------------------------------------------------------------

    def _build_entry_row(self, text: str, timestamp: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("history-row")
        row.set_margin_start(14)
        row.set_margin_end(14)
        row.set_margin_top(10)
        row.set_margin_bottom(10)

        # Text column.
        text_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_col.set_hexpand(True)

        text_label = Gtk.Label(label=text)
        text_label.add_css_class("history-text")
        text_label.set_halign(Gtk.Align.START)
        text_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        text_label.set_max_width_chars(35)
        text_label.set_lines(1)
        _apply_font_size(text_label, 12)
        text_col.append(text_label)

        if timestamp:
            time_label = Gtk.Label(label=timestamp)
            time_label.add_css_class("text-muted")
            time_label.set_halign(Gtk.Align.START)
            _apply_font_size(time_label, 10)
            text_col.append(time_label)

        row.append(text_col)

        # Copy button.
        copy_btn = Gtk.Button()
        copy_btn.add_css_class("icon-btn")
        copy_icon = Gtk.Image.new_from_icon_name("edit-copy-symbolic")
        copy_icon.set_pixel_size(14)
        copy_icon.add_css_class("text-muted")
        copy_btn.set_child(copy_icon)
        copy_btn.set_valign(Gtk.Align.CENTER)
        copy_btn.connect("clicked", self._on_copy_clicked, text)
        row.append(copy_btn)

        return row

    def _show_empty_state(self) -> None:
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.set_size_request(-1, _EMPTY_HEIGHT)

        icon = Gtk.Image.new_from_icon_name("mail-unread-symbolic")
        icon.set_pixel_size(24)
        icon.add_css_class("text-muted")
        empty_box.append(icon)

        label = Gtk.Label(
            label=i18n.t("indicator.history_empty", fallback="No voice input history yet")
        )
        label.add_css_class("text-muted")
        _apply_font_size(label, 13)
        empty_box.append(label)

        self._entries_box.append(empty_box)

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def _on_copy_clicked(self, button: Gtk.Button, text: str) -> None:
        """Copy text to the X11 clipboard using xclip."""
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=text.encode("utf-8"), timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("xclip timed out; killing process.")
            proc.kill()
            proc.wait()
            return
        except FileNotFoundError:
            logger.warning("xclip not found; cannot copy to clipboard.")
            return

        # Show a brief toast.
        from bytecli.indicator.toast_manager import ToastManager

        ToastManager.instance().show_toast(
            "success",
            i18n.t("toast.copied", fallback="Copied to clipboard"),
        )

    # ------------------------------------------------------------------
    # Panel CSS
    # ------------------------------------------------------------------

    def _apply_panel_css(self) -> None:
        provider = Gtk.CssProvider()
        css = (
            ".history-panel {"
            "  background-color: #1A1A1A;"
            "  border-radius: 12px;"
            "  border: 1px solid #2E2E2E;"
            "}"
        )
        provider.load_from_data(css.encode())
        self._outer_box.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _apply_font_size(widget: Gtk.Widget, size_px: int) -> None:
    provider = Gtk.CssProvider()
    css = f"* {{ font-size: {size_px}px; }}"
    provider.load_from_data(css.encode())
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
