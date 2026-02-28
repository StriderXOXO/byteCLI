"""
ModelSelectionSection -- Whisper model picker (tiny / small / medium).

Displays three RadioOption rows and handles the asynchronous model
switching workflow, including spinner, checkmark, failure states and
auto-revert on error.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from bytecli.constants import WHISPER_MODELS
from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard
from bytecli.settings.widgets.radio_option import RadioOption

logger = logging.getLogger(__name__)

# Model keys in display order.
_MODEL_ORDER = ["tiny", "small", "medium"]


class ModelSelectionSection(Gtk.Box):
    """Three-option radio group for Whisper model selection."""

    def __init__(
        self,
        dbus_client: DBusClient,
        config: dict[str, Any],
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._dbus_client = dbus_client
        self._config = config
        self._on_changed = on_changed
        self._switching = False
        self._previous_model: Optional[str] = None

        self._card = SectionCard(
            title=i18n.t("settings.model.title", fallback="Model Selection")
        )

        self._radios: dict[str, RadioOption] = {}
        for key in _MODEL_ORDER:
            meta = WHISPER_MODELS[key]
            display = meta["display_name"]
            size = meta["size"]
            is_recommended = key == "small"
            desc = (
                i18n.t("settings.model.recommended", fallback="Recommended")
                if is_recommended
                else size
            )

            radio = RadioOption(
                label_text=display,
                description_text=desc,
                on_clicked=lambda r, k=key: self._on_radio_clicked(k),
                highlight_description=is_recommended,
            )
            self._radios[key] = radio
            self._card.card_content.append(radio)

        self.append(self._card)

        # Set initial selection from config.
        self._apply_selection(config.get("model", "small"))

        # Listen for model-switch progress from D-Bus.
        self._dbus_client.subscribe_signal(
            "ModelSwitchProgress", self._on_switch_progress
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _apply_selection(self, model_key: str) -> None:
        for key, radio in self._radios.items():
            radio.selected = key == model_key

    def _on_radio_clicked(self, key: str) -> None:
        if self._switching:
            return

        self._previous_model = self._config.get("model", "small")
        self._config["model"] = key
        self._apply_selection(key)
        self._on_changed()

        # Begin the async model switch.
        self._switching = True
        self._set_switching_ui(key)
        self._dbus_client.switch_model(key, callback=self._on_switch_result)

    def _set_switching_ui(self, active_key: str) -> None:
        for key, radio in self._radios.items():
            if key == active_key:
                radio.show_spinner()
                radio.disabled = False
            else:
                radio.disabled = True

    def _restore_ui(self) -> None:
        for radio in self._radios.values():
            radio.disabled = False
            radio._clear_status()

    # ------------------------------------------------------------------
    # D-Bus callbacks
    # ------------------------------------------------------------------

    def _on_switch_result(self, result) -> None:
        self._switching = False
        if result is not None:
            self._on_switch_success()
        else:
            self._on_switch_failed()

    def _on_switch_progress(self, conn, sender, path, iface, signal_name, params) -> None:
        """Handle intermediate progress signals during model download."""
        pass  # Could update a progress bar in future.

    def _on_switch_success(self) -> None:
        current = self._config.get("model", "small")
        if current in self._radios:
            self._radios[current].show_checkmark(duration_ms=2000)
        GLib.timeout_add(2000, self._restore_ui)

    def _on_switch_failed(self) -> None:
        current = self._config.get("model", "small")
        if current in self._radios:
            self._radios[current].show_x_mark()

        # Revert to previous model.
        if self._previous_model:
            self._config["model"] = self._previous_model
            self._apply_selection(self._previous_model)
            self._on_changed()

        GLib.timeout_add(2000, self._restore_ui)

    # ------------------------------------------------------------------
    # Config interface
    # ------------------------------------------------------------------

    def collect_config(self, config: dict) -> None:
        config["model"] = self._config.get("model", "small")

    def apply_config(self, config: dict) -> None:
        self._config["model"] = config.get("model", "small")
        self._apply_selection(self._config["model"])

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("settings.model.title", fallback="Model Selection")
        )
