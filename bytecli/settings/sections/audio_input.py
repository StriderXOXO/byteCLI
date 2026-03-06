"""
AudioInputSection -- audio input device selector with hotplug support.

Populates a dropdown from ``dbus_client.get_audio_devices()`` which
returns a list of ``(id, name)`` tuples.  The first entry is always
"Auto (System Default)".

Subscribes to ``AudioDeviceChanged`` D-Bus signal so the device list
stays current when hardware is plugged or unplugged at runtime.

When no real devices are detected the dropdown shows a red border and a
warning icon with "No devices detected" text.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard

logger = logging.getLogger(__name__)

# Sentinel config value for the "auto" device selection.
_AUTO_DEVICE_ID = "auto"


class AudioInputSection(Gtk.Box):
    """Audio input device selector with live hotplug update support."""

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

        # Internal device list: list of (device_id, display_name) tuples.
        # Does NOT include the synthetic "Auto" entry.
        self._devices: list[tuple[str, str]] = []

        # Guard against callback storms during programmatic updates.
        self._suppress_signal = False

        self._card = SectionCard(
            title=i18n.t("audio.label", fallback="Audio Input")
        )

        # --- Dropdown row ---
        self._dropdown = Gtk.ComboBoxText()
        self._dropdown.get_style_context().add_class("dropdown-btn")
        self._dropdown.set_hexpand(True)
        self._dropdown.connect("changed", self._on_selection_changed)
        self._card.card_content.pack_start(self._dropdown, False, False, 0)

        # --- No-device warning (hidden by default) ---
        self._error_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._error_box.set_margin_top(6)
        self._error_box.set_visible(False)

        error_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic", Gtk.IconSize.BUTTON)
        error_icon.set_pixel_size(14)
        error_icon.get_style_context().add_class("text-error")
        self._error_box.pack_start(error_icon, False, False, 0)

        self._error_label = Gtk.Label(
            label=i18n.t("audio.no_devices", fallback="No devices detected")
        )
        self._error_label.get_style_context().add_class("text-error")
        self._error_label.get_style_context().add_class("text-sm")
        self._error_label.set_halign(Gtk.Align.START)
        self._error_box.pack_start(self._error_label, False, False, 0)

        self._error_box.set_no_show_all(True)
        self._card.card_content.pack_start(self._error_box, False, False, 0)

        # Hint text below the error.
        self._hint_label = Gtk.Label(
            label=i18n.t(
                "audio.no_devices_hint",
                fallback="Connect a microphone and restart the service.",
            )
        )
        self._hint_label.get_style_context().add_class("text-muted")
        self._hint_label.get_style_context().add_class("text-sm")
        self._hint_label.set_halign(Gtk.Align.START)
        self._hint_label.set_margin_top(2)
        self._hint_label.set_no_show_all(True)
        self._hint_label.set_visible(False)
        self._card.card_content.pack_start(self._hint_label, False, False, 0)

        self.pack_start(self._card, False, False, 0)

        # Subscribe to hotplug signal.
        self._dbus_client.subscribe_signal(
            "AudioDeviceChanged", self._on_device_changed_signal
        )

        # Populate devices on first load.
        self._populate_devices()

    # ------------------------------------------------------------------
    # Device population
    # ------------------------------------------------------------------

    def _populate_devices(self) -> None:
        """Fetch the device list from the D-Bus service and rebuild the UI.

        Falls back to local detection via ``sounddevice`` when the
        service is unreachable.
        """
        raw = self._dbus_client.get_audio_devices()
        if raw is None:
            raw = self._detect_devices_locally()
        if raw is None:
            raw = []

        # Normalise to list of (id, name) tuples.
        devices: list[tuple[str, str]] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                devices.append((str(item[0]), str(item[1])))
            elif isinstance(item, str):
                devices.append((item, item))

        self._devices = devices
        self._rebuild_dropdown()

    @staticmethod
    def _detect_devices_locally():
        """Detect input devices locally using sounddevice."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            result = []
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    result.append((str(idx), dev["name"]))
            if result:
                logger.info("Detected %d input device(s) locally.", len(result))
                return result
        except Exception as exc:
            logger.warning("Local audio device detection failed: %s", exc)
        return None

    def _rebuild_dropdown(self) -> None:
        """Repopulate the dropdown StringList from ``self._devices``."""
        self._suppress_signal = True

        # Clear the existing model.
        self._dropdown.remove_all()

        # "Auto" is always the first entry.
        auto_label = i18n.t("audio.auto", fallback="Auto (System Default)")
        self._dropdown.append_text(auto_label)

        for _dev_id, dev_name in self._devices:
            self._dropdown.append_text(dev_name)

        # Select the entry matching the current config value.
        current_id = self._config.get("audio_input", _AUTO_DEVICE_ID)
        selected_index = 0  # default to Auto
        if current_id != _AUTO_DEVICE_ID:
            for idx, (dev_id, _) in enumerate(self._devices):
                if dev_id == current_id:
                    selected_index = idx + 1  # +1 because Auto is at index 0
                    break

        self._dropdown.set_active(selected_index)

        # Show or hide no-device warning.
        has_real_devices = len(self._devices) > 0
        self._error_box.set_visible(not has_real_devices)
        self._hint_label.set_visible(not has_real_devices)
        if not has_real_devices:
            self._dropdown.get_style_context().add_class("text-error")
        else:
            self._dropdown.get_style_context().remove_class("text-error")

        self._suppress_signal = False

    # ------------------------------------------------------------------
    # Selection handling
    # ------------------------------------------------------------------

    def _on_selection_changed(self, combo) -> None:
        if self._suppress_signal:
            return

        idx = combo.get_active()
        if idx == 0 or idx < 0:
            self._config["audio_input"] = _AUTO_DEVICE_ID
        else:
            device_idx = idx - 1
            if 0 <= device_idx < len(self._devices):
                self._config["audio_input"] = self._devices[device_idx][0]
            else:
                self._config["audio_input"] = _AUTO_DEVICE_ID

        self._on_changed()

    # ------------------------------------------------------------------
    # D-Bus signal
    # ------------------------------------------------------------------

    def _on_device_changed_signal(
        self, conn, sender, path, iface, signal_name, params
    ) -> None:
        """Repopulate the device list when the service detects a hotplug event."""
        logger.debug("AudioDeviceChanged signal received; refreshing device list.")
        self._populate_devices()

    # ------------------------------------------------------------------
    # Config interface (called by SettingsWindow)
    # ------------------------------------------------------------------

    def collect_config(self, config: dict) -> None:
        config["audio_input"] = self._config.get("audio_input", _AUTO_DEVICE_ID)

    def apply_config(self, config: dict) -> None:
        self._config["audio_input"] = config.get("audio_input", _AUTO_DEVICE_ID)
        self._rebuild_dropdown()

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("audio.label", fallback="Audio Input")
        )
        self._error_label.set_text(
            i18n.t("audio.no_devices", fallback="No devices detected")
        )
        self._hint_label.set_text(
            i18n.t(
                "audio.no_devices_hint",
                fallback="Connect a microphone and restart the service.",
            )
        )
        # Rebuild to refresh the "Auto" label.
        self._rebuild_dropdown()
