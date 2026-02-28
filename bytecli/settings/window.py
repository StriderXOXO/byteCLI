"""
SettingsWindow -- main settings panel for ByteCLI.

A fixed-width Adw.ApplicationWindow containing all seven configuration
sections arranged vertically in a scrolled container.  Connects to the
ByteCLI D-Bus service on init, loads the current configuration, and
provides Save / Cancel buttons that compare the live values against a
snapshot taken when the window was opened.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

from bytecli.constants import DEFAULT_CONFIG
from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient

from bytecli.settings.sections.server_status import ServerStatusSection
from bytecli.settings.sections.model_selection import ModelSelectionSection
from bytecli.settings.sections.device_selection import DeviceSelectionSection
from bytecli.settings.sections.audio_input import AudioInputSection
from bytecli.settings.sections.hotkey_config import HotkeyConfigSection
from bytecli.settings.sections.language_select import LanguageSelectSection
from bytecli.settings.sections.startup_config import StartupConfigSection
from bytecli.settings.widgets.styled_button import StyledButton
from bytecli.settings.widgets.toast_overlay import SettingsToastOverlay

logger = logging.getLogger(__name__)


class SettingsWindow(Adw.ApplicationWindow):
    """Fixed-width settings panel with scrollable sections."""

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application)

        self.set_default_size(480, 1150)
        self.set_resizable(False)
        self.set_title(i18n.t("settings.title", fallback="Voice Dictation Settings"))

        # Apply window CSS.
        self.add_css_class("settings-window")
        self._apply_window_css()

        # D-Bus client.
        self._dbus_client = DBusClient()
        self._dbus_client.connect()

        # Configuration state.
        self._config: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self._config_snapshot: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self._load_config()

        # Build the UI.
        self._build_ui()

        # Register for i18n changes.
        i18n.on_language_changed(self._on_language_changed)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Overlay for in-window toasts.
        self._overlay = Gtk.Overlay()
        self._toast_overlay = SettingsToastOverlay(self._overlay)

        # Scrolled container.
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        # Main content box.
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self._content_box.set_margin_start(24)
        self._content_box.set_margin_end(24)
        self._content_box.set_margin_top(24)
        self._content_box.set_margin_bottom(24)

        # Title.
        self._title_label = Gtk.Label(
            label=i18n.t("settings.title", fallback="Voice Dictation Settings")
        )
        self._title_label.add_css_class("mono")
        self._title_label.add_css_class("font-semibold")
        self._title_label.add_css_class("text-xl")
        self._title_label.set_halign(Gtk.Align.START)
        self._content_box.append(self._title_label)

        # --- Sections ---
        self._server_section = ServerStatusSection(self._dbus_client)
        self._content_box.append(self._server_section)

        self._model_section = ModelSelectionSection(
            self._dbus_client, self._config, self._on_config_value_changed
        )
        self._content_box.append(self._model_section)

        self._device_section = DeviceSelectionSection(
            self._dbus_client, self._config, self._on_config_value_changed
        )
        self._content_box.append(self._device_section)

        self._audio_section = AudioInputSection(
            self._dbus_client, self._config, self._on_config_value_changed
        )
        self._content_box.append(self._audio_section)

        self._hotkey_section = HotkeyConfigSection(
            self._dbus_client, self._config, self._on_config_value_changed
        )
        self._content_box.append(self._hotkey_section)

        self._language_section = LanguageSelectSection(
            self._dbus_client, self._config
        )
        self._content_box.append(self._language_section)

        self._startup_section = StartupConfigSection(self._config)
        self._content_box.append(self._startup_section)

        # --- Save / Cancel row ---
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_margin_top(8)

        self._cancel_btn = StyledButton(
            label=i18n.t("settings.cancel", fallback="Cancel"),
            variant="secondary",
        )
        self._cancel_btn.connect("clicked", self._on_cancel)
        self._cancel_btn.set_disabled(True)
        btn_row.append(self._cancel_btn)

        self._save_btn = StyledButton(
            label=i18n.t("settings.save", fallback="Save"),
            variant="primary",
        )
        self._save_btn.connect("clicked", self._on_save)
        self._save_btn.set_disabled(True)
        btn_row.append(self._save_btn)

        self._content_box.append(btn_row)

        scroll.set_child(self._content_box)
        self._overlay.set_child(scroll)
        self.set_content(self._overlay)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Fetch config from the service D-Bus interface."""
        remote = self._dbus_client.get_config()
        if remote is not None:
            self._config = remote
        else:
            logger.warning("Could not load remote config; using defaults.")
            self._config = copy.deepcopy(DEFAULT_CONFIG)
        self._config_snapshot = copy.deepcopy(self._config)

    def _on_config_value_changed(self) -> None:
        """Callback invoked by child sections when a config value changes."""
        self._update_save_cancel()

    def _update_save_cancel(self) -> None:
        """Enable Save/Cancel only when live config differs from snapshot."""
        changed = self._config != self._config_snapshot
        self._save_btn.set_disabled(not changed)
        self._cancel_btn.set_disabled(not changed)

    # ------------------------------------------------------------------
    # Save / Cancel
    # ------------------------------------------------------------------

    def _on_save(self, button: Gtk.Button) -> None:
        """Collect all section values and push to the service."""
        # Collect values from sections.
        self._model_section.collect_config(self._config)
        self._device_section.collect_config(self._config)
        self._audio_section.collect_config(self._config)
        self._hotkey_section.collect_config(self._config)
        self._startup_section.collect_config(self._config)

        def _on_saved(result):
            if result is not None:
                self._config_snapshot = copy.deepcopy(self._config)
                self._update_save_cancel()
                self._toast_overlay.show_toast(
                    i18n.t("settings.saved", fallback="Settings saved successfully"),
                    variant="success",
                )
            else:
                self._toast_overlay.show_toast(
                    i18n.t("settings.save_failed", fallback="Failed to save settings"),
                    variant="error",
                )

        self._dbus_client.save_config(self._config, callback=_on_saved)

    def _on_cancel(self, button: Gtk.Button) -> None:
        """Restore all sections to the snapshot values."""
        self._config = copy.deepcopy(self._config_snapshot)
        self._model_section.apply_config(self._config)
        self._device_section.apply_config(self._config)
        self._audio_section.apply_config(self._config)
        self._hotkey_section.apply_config(self._config)
        self._startup_section.apply_config(self._config)
        self._update_save_cancel()

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def _on_language_changed(self, lang: str) -> None:
        """Refresh all labels when the interface language changes."""
        self._title_label.set_text(
            i18n.t("settings.title", fallback="Voice Dictation Settings")
        )
        self._save_btn.set_label(i18n.t("settings.save", fallback="Save"))
        self._cancel_btn.set_label(i18n.t("settings.cancel", fallback="Cancel"))

        # Propagate to sections that support refresh.
        for section in (
            self._server_section,
            self._model_section,
            self._device_section,
            self._audio_section,
            self._hotkey_section,
            self._language_section,
            self._startup_section,
        ):
            if hasattr(section, "refresh_labels"):
                section.refresh_labels()

    # ------------------------------------------------------------------
    # Window CSS
    # ------------------------------------------------------------------

    def _apply_window_css(self) -> None:
        provider = Gtk.CssProvider()
        css = (
            ".settings-window {"
            "  background-color: #1A1A1A;"
            "  border-radius: 16px;"
            "  border: 1px solid #2E2E2E;"
            "}"
        )
        provider.load_from_data(css.encode())
        self.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
