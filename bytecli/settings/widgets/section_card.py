"""
SectionCard -- reusable card container for settings sections.

Provides a titled card with a dark inner frame matching the ByteCLI
design system.  Title uses JetBrains Mono at 15px 600 weight.  The
card body has background #1A1A1A, 1px #2E2E2E border, 8px corner
radius and 16px padding.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk


class SectionCard(Gtk.Box):
    """Vertical layout with a title label and a styled card frame.

    Parameters
    ----------
    title:
        Section heading text displayed above the card.
    gap:
        Vertical spacing between rows inside the card content area.
    """

    def __init__(self, title: str, gap: int = 12) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        # Section title -- JetBrains Mono 15px 600 weight.
        self._title_label = Gtk.Label(label=title)
        self._title_label.get_style_context().add_class("mono")
        self._title_label.get_style_context().add_class("font-semibold")
        self._title_label.set_halign(Gtk.Align.START)
        self._apply_title_css()
        self.pack_start(self._title_label, False, False, 0)

        # Card frame -- bg #1A1A1A, border 1px #2E2E2E, radius 8px, pad 16px.
        self._card_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._card_frame.get_style_context().add_class("section-card-inner")

        # Inner content box that consumers add widgets to.
        self.card_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=gap)
        self._card_frame.pack_start(self.card_content, False, False, 0)

        self.pack_start(self._card_frame, False, False, 0)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def title_label(self) -> Gtk.Label:
        return self._title_label

    def set_title(self, title: str) -> None:
        self._title_label.set_text(title)

    def add_row(self, widget: Gtk.Widget) -> None:
        """Append *widget* as a new row inside the card content area."""
        self.card_content.pack_start(widget, False, False, 0)

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_title_css(self) -> None:
        """Apply 15px font size to the title label."""
        provider = Gtk.CssProvider()
        css = "* { font-size: 15px; }"
        provider.load_from_data(css.encode())
        self._title_label.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
