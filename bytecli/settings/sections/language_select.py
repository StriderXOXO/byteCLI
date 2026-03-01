"""
LanguageSelectSection -- interface language dropdown.

Switches the i18n language immediately on selection (no Save required)
and persists the choice to the service configuration independently via
a ``save_config`` D-Bus call.

Supported languages:
    en -- English
    zh -- Chinese
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard

logger = logging.getLogger(__name__)

# Supported languages: (code, display_name).
_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("zh", "\u4e2d\u6587"),  # Chinese
]


class LanguageSelectSection(Gtk.Box):
    """Interface language dropdown that applies immediately."""

    def __init__(
        self,
        dbus_client: DBusClient,
        config: dict[str, Any],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._dbus_client = dbus_client
        self._config = config
        self._suppress_signal = False

        self._card = SectionCard(
            title=i18n.t("lang.label", fallback="Language")
        )

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_valign(Gtk.Align.CENTER)

        self._row_label = Gtk.Label(
            label=i18n.t(
                "lang.interface",
                fallback="Interface Language:",
            )
        )
        self._row_label.add_css_class("text-base")
        self._row_label.set_halign(Gtk.Align.START)
        row.append(self._row_label)

        self._lang_list = Gtk.StringList()
        for _code, display in _LANGUAGES:
            self._lang_list.append(display)

        self._dropdown = Gtk.DropDown(model=self._lang_list)
        self._dropdown.add_css_class("dropdown-btn")
        self._dropdown.set_hexpand(True)
        self._dropdown.connect("notify::selected", self._on_selection_changed)
        row.append(self._dropdown)

        self._card.card_content.append(row)
        self.append(self._card)

        # Set initial value from config.
        current_lang = config.get("language", "en")
        self._suppress_signal = True
        for idx, (code, _) in enumerate(_LANGUAGES):
            if code == current_lang:
                self._dropdown.set_selected(idx)
                break
        self._suppress_signal = False

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _on_selection_changed(self, dropdown, param) -> None:
        if self._suppress_signal:
            return

        idx = dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(_LANGUAGES):
            return

        code, _ = _LANGUAGES[idx]
        self._config["language"] = code

        # Switch the interface language immediately.
        # This fires i18n callbacks across all registered widgets.
        i18n.switch(code)

        # Persist the language choice independently so it survives a
        # Cancel click -- language preference is applied instantly.
        self._persist_language(code)

    def _persist_language(self, lang_code: str) -> None:
        """Save just the language choice to the service via D-Bus."""
        config_snapshot = copy.deepcopy(self._config)
        config_snapshot["language"] = lang_code

        def _on_done(result):
            if result is None:
                logger.warning(
                    "Failed to persist language preference '%s'.", lang_code
                )

        self._dbus_client.save_config(config_snapshot, callback=_on_done)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("lang.label", fallback="Language")
        )
        self._row_label.set_text(
            i18n.t(
                "lang.interface",
                fallback="Interface Language:",
            )
        )
