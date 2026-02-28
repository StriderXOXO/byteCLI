"""
RadioOption -- custom radio row widget for model / device selection.

Provides a hand-drawn radio indicator (16x16 circle), a label with
optional description text, and a status indicator area that shows a
spinner, checkmark or X-mark during asynchronous switching operations.

Constructor:
    RadioOption(label, description, group=None)

The ``group`` parameter links multiple RadioOption instances so that
selecting one deselects the others -- the same semantics as
Gtk.CheckButton radio groups, but managed manually.

Status API:
    ``set_status(status)`` where *status* is one of
    ``"none"``, ``"switching"``, ``"success"``, ``"failed"``.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk


class RadioOption(Gtk.Box):
    """Custom radio-button row with status indicator support.

    Parameters
    ----------
    label_text:
        Primary label displayed next to the radio indicator.
    description_text:
        Secondary description shown beside the label (e.g. model size
        or a "Recommended" tag).
    group:
        Another ``RadioOption`` instance to link into a mutual
        exclusion group with.  When this option is selected every
        other option in the same group is deselected.
    on_clicked:
        Optional callback invoked with ``self`` when the user clicks
        an unselected, enabled row.
    highlight_description:
        When *True* the description text uses the primary orange
        colour instead of the muted colour.
    """

    def __init__(
        self,
        label_text: str,
        description_text: str = "",
        group: Optional["RadioOption"] = None,
        on_clicked: Optional[Callable[["RadioOption"], None]] = None,
        highlight_description: bool = False,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("radio-row")
        self.set_hexpand(True)

        self._selected = False
        self._disabled = False
        self._on_clicked = on_clicked
        self._label_text = label_text
        self._description_text = description_text

        # Group management: all members share a single list reference.
        if group is not None:
            self._group: list[RadioOption] = group._group
        else:
            self._group = []
        self._group.append(self)

        # Radio indicator (16x16 drawn circle).
        self._radio_dot = Gtk.DrawingArea()
        self._radio_dot.set_size_request(16, 16)
        self._radio_dot.set_valign(Gtk.Align.CENTER)
        self._radio_dot.set_draw_func(self._draw_radio)
        self.append(self._radio_dot)

        # Text column.
        text_col = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        text_col.set_valign(Gtk.Align.CENTER)
        text_col.set_hexpand(True)

        self._label = Gtk.Label(label=label_text)
        self._label.add_css_class("text-base")
        self._label.set_halign(Gtk.Align.START)
        text_col.append(self._label)

        if description_text:
            self._description = Gtk.Label(label=description_text)
            self._description.set_halign(Gtk.Align.START)
            _apply_font_size(self._description, 13)
            if highlight_description:
                self._description.add_css_class("text-primary")
            else:
                self._description.add_css_class("text-muted")
            text_col.append(self._description)
        else:
            self._description = None

        self.append(text_col)

        # Status indicator area (spinner / checkmark / x-mark).
        self._status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._status_box.set_valign(Gtk.Align.CENTER)
        self._status_box.set_size_request(24, 24)
        self.append(self._status_box)

        # Click handling via GestureClick.
        gesture = Gtk.GestureClick()
        gesture.connect("released", self._on_click)
        self.add_controller(gesture)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value
        if value:
            self.add_css_class("radio-row-active")
            # Deselect all other members of the group.
            for sibling in self._group:
                if sibling is not self and sibling._selected:
                    sibling._selected = False
                    sibling.remove_css_class("radio-row-active")
                    sibling._radio_dot.queue_draw()
        else:
            self.remove_css_class("radio-row-active")
        self._radio_dot.queue_draw()

    @property
    def disabled(self) -> bool:
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool) -> None:
        self._disabled = value
        self.set_sensitive(not value)
        if value:
            self.set_opacity(0.4)
        else:
            self.set_opacity(1.0)

    @property
    def label_text(self) -> str:
        return self._label_text

    @label_text.setter
    def label_text(self, value: str) -> None:
        self._label_text = value
        self._label.set_text(value)

    @property
    def description_text(self) -> str:
        return self._description_text

    @description_text.setter
    def description_text(self, value: str) -> None:
        self._description_text = value
        if self._description is not None:
            self._description.set_text(value)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_radio(self, area, cr, width, height) -> None:
        cx = width / 2.0
        cy = height / 2.0
        radius = min(width, height) / 2.0 - 1

        # Outer circle border.
        if self._selected:
            cr.set_source_rgba(1.0, 0.518, 0.0, 1.0)  # #FF8400
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)  # white border
        cr.set_line_width(1.5)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        # Inner filled dot when selected.
        if self._selected:
            cr.set_source_rgba(1.0, 0.518, 0.0, 1.0)
            cr.arc(cx, cy, radius * 0.5, 0, 2 * math.pi)
            cr.fill()

    # ------------------------------------------------------------------
    # Click handling
    # ------------------------------------------------------------------

    def _on_click(self, gesture, n_press, x, y) -> None:
        if self._disabled or self._selected:
            return
        if self._on_clicked is not None:
            self._on_clicked(self)

    # ------------------------------------------------------------------
    # Status indicators -- high-level API
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        """Set the status indicator.

        Parameters
        ----------
        status:
            ``"none"``      -- clear any indicator.
            ``"switching"`` -- show a loading spinner.
            ``"success"``   -- show a green checkmark for 2 s then clear.
            ``"failed"``    -- show a red X mark.
        """
        if status == "none":
            self._clear_status()
        elif status == "switching":
            self.show_spinner()
        elif status == "success":
            self.show_checkmark(duration_ms=2000)
        elif status == "failed":
            self.show_x_mark()
        else:
            self._clear_status()

    # ------------------------------------------------------------------
    # Status indicators -- low-level API
    # ------------------------------------------------------------------

    def show_spinner(self) -> None:
        """Show a loading spinner in the status area."""
        self._clear_status()
        spinner = Gtk.Spinner()
        spinner.set_size_request(16, 16)
        spinner.start()
        self._status_box.append(spinner)

    def show_checkmark(self, duration_ms: int = 2000) -> None:
        """Show a green checkmark, then clear after *duration_ms*."""
        self._clear_status()
        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        icon.set_pixel_size(16)
        icon.add_css_class("text-success")
        self._status_box.append(icon)
        GLib.timeout_add(duration_ms, self._clear_status)

    def show_x_mark(self) -> None:
        """Show a red X icon in the status area."""
        self._clear_status()
        icon = Gtk.Image.new_from_icon_name("process-stop-symbolic")
        icon.set_pixel_size(16)
        icon.add_css_class("text-error")
        self._status_box.append(icon)

    def _clear_status(self) -> bool:
        child = self._status_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._status_box.remove(child)
            child = next_child
        return False  # for use as GLib timeout callback


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
