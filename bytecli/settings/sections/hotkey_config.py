"""
HotkeyConfigSection -- displays the fixed Ctrl+Alt+V hotkey binding.

The hotkey is not user-configurable; this section simply shows the
current binding as a read-only label.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from bytecli.i18n import i18n
from bytecli.settings.widgets.section_card import SectionCard


class HotkeyConfigSection(Gtk.Box):
    """Read-only display of the fixed Ctrl+Alt+V hotkey."""

    def __init__(self, **_kwargs) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._card = SectionCard(
            title=i18n.t("hotkey.label", fallback="Hotkey")
        )

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_valign(Gtk.Align.CENTER)

        self._trigger_label = Gtk.Label(
            label=i18n.t("hotkey.trigger_key", fallback="Trigger Key:")
        )
        self._trigger_label.get_style_context().add_class("text-base")
        self._trigger_label.get_style_context().add_class("text-muted")
        self._trigger_label.set_halign(Gtk.Align.START)
        row.pack_start(self._trigger_label, False, False, 0)

        value_label = Gtk.Label(label="Ctrl + Alt + V")
        value_label.get_style_context().add_class("mono")
        value_label.get_style_context().add_class("font-semibold")
        value_label.set_halign(Gtk.Align.START)
        row.pack_start(value_label, False, False, 0)

        self._card.card_content.pack_start(row, False, False, 0)
        self.pack_start(self._card, False, False, 0)

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("hotkey.label", fallback="Hotkey")
        )
        self._trigger_label.set_text(
            i18n.t("hotkey.trigger_key", fallback="Trigger Key:")
        )
