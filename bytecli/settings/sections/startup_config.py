"""
StartupConfigSection -- auto-start toggle for ByteCLI.

Manages a ``.desktop`` file in ``~/.config/autostart/`` to control
whether ByteCLI launches automatically on system boot / login.

The toggle creates or deletes the desktop entry immediately and
also updates ``config["auto_start"]`` so the preference is included
in the next Save.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from bytecli.i18n import i18n
from bytecli.settings.widgets.section_card import SectionCard

logger = logging.getLogger(__name__)

_AUTOSTART_DIR: str = os.path.expanduser("~/.config/autostart")
_AUTOSTART_FILE: str = os.path.join(_AUTOSTART_DIR, "bytecli.desktop")

_DESKTOP_ENTRY: str = """\
[Desktop Entry]
Type=Application
Name=ByteCLI Voice Dictation
Comment=Local voice-to-text dictation tool
Exec=bytecli-service
Icon=audio-input-microphone
Terminal=false
Categories=Utility;Accessibility;
X-GNOME-Autostart-enabled=true
"""


class StartupConfigSection(Gtk.Box):
    """Toggle switch for system-boot autostart."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._config = config
        self._suppress_signal = False

        self._card = SectionCard(
            title=i18n.t("startup.label", fallback="Startup")
        )

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_valign(Gtk.Align.CENTER)

        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch.connect("notify::active", self._on_toggled)
        row.pack_start(self._switch, False, False, 0)

        self._label = Gtk.Label(
            label=i18n.t(
                "startup.auto",
                fallback="Start automatically on system boot",
            )
        )
        self._label.get_style_context().add_class("text-base")
        self._label.set_halign(Gtk.Align.START)
        self._label.set_hexpand(True)
        row.pack_start(self._label, True, True, 0)

        self._card.card_content.pack_start(row, False, False, 0)
        self.pack_start(self._card, False, False, 0)

        # Set initial state from config.
        auto = config.get("auto_start", False)
        self._suppress_signal = True
        self._switch.set_active(auto)
        self._suppress_signal = False

    # ------------------------------------------------------------------
    # Toggle handling
    # ------------------------------------------------------------------

    def _on_toggled(self, switch, param) -> None:
        if self._suppress_signal:
            return

        active = switch.get_active()
        self._config["auto_start"] = active

        if active:
            self._install_autostart()
        else:
            self._remove_autostart()

    # ------------------------------------------------------------------
    # Autostart file management
    # ------------------------------------------------------------------

    @staticmethod
    def _install_autostart() -> None:
        """Write the .desktop file to the autostart directory."""
        try:
            os.makedirs(_AUTOSTART_DIR, exist_ok=True)
            with open(_AUTOSTART_FILE, "w", encoding="utf-8") as fh:
                fh.write(_DESKTOP_ENTRY)
            logger.info("Autostart desktop entry created: %s", _AUTOSTART_FILE)
        except OSError as exc:
            logger.error("Failed to create autostart entry: %s", exc)

    @staticmethod
    def _remove_autostart() -> None:
        """Delete the .desktop file from the autostart directory."""
        try:
            if os.path.isfile(_AUTOSTART_FILE):
                os.unlink(_AUTOSTART_FILE)
                logger.info(
                    "Autostart desktop entry removed: %s", _AUTOSTART_FILE
                )
        except OSError as exc:
            logger.error("Failed to remove autostart entry: %s", exc)

    # ------------------------------------------------------------------
    # Config interface (called by SettingsWindow)
    # ------------------------------------------------------------------

    def collect_config(self, config: dict) -> None:
        config["auto_start"] = self._switch.get_active()

    def apply_config(self, config: dict) -> None:
        self._suppress_signal = True
        self._config["auto_start"] = config.get("auto_start", False)
        self._switch.set_active(self._config["auto_start"])
        self._suppress_signal = False

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("startup.label", fallback="Startup")
        )
        self._label.set_text(
            i18n.t(
                "startup.auto",
                fallback="Start automatically on system boot",
            )
        )
