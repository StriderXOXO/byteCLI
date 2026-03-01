"""
DeviceSelectionSection -- GPU (CUDA) vs CPU device picker.

On init, probes for CUDA availability.  If CUDA is not detected the GPU
option is disabled and CPU is auto-selected with a red warning message.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard
from bytecli.settings.widgets.radio_option import RadioOption

logger = logging.getLogger(__name__)


def _cuda_available() -> bool:
    """Check if CUDA is available via PyTorch."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


class DeviceSelectionSection(Gtk.Box):
    """Two-option radio group for compute device selection."""

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
        self._previous_device: Optional[str] = None
        self._has_cuda = _cuda_available()
        self._restore_timeout_id: Optional[int] = None
        self._switch_timeout_id: Optional[int] = None

        self._card = SectionCard(
            title=i18n.t("device.label", fallback="Device")
        )

        # GPU option.
        self._gpu_radio = RadioOption(
            label_text=i18n.t("device.gpu", fallback="GPU (CUDA)"),
            description_text="",
            on_clicked=lambda r: self._on_radio_clicked("gpu"),
        )
        self._card.card_content.append(self._gpu_radio)

        # CPU option.
        self._cpu_radio = RadioOption(
            label_text=i18n.t("device.cpu", fallback="CPU"),
            description_text="",
            on_clicked=lambda r: self._on_radio_clicked("cpu"),
        )
        self._card.card_content.append(self._cpu_radio)

        # Warning label for missing CUDA.
        self._cuda_warning = Gtk.Label()
        self._cuda_warning.add_css_class("text-error")
        self._cuda_warning.add_css_class("text-sm")
        self._cuda_warning.set_halign(Gtk.Align.START)
        self._cuda_warning.set_margin_top(4)
        self._cuda_warning.set_visible(False)
        self._card.card_content.append(self._cuda_warning)

        self.append(self._card)

        # Apply initial state.
        if not self._has_cuda:
            self._gpu_radio.disabled = True
            self._cuda_warning.set_text(
                i18n.t("device.cuda_not_detected", fallback="CUDA not detected")
            )
            self._cuda_warning.set_visible(True)
            self._config["device"] = "cpu"
            self._cpu_radio.description_text = i18n.t(
                "device.auto_selected", fallback="(auto-selected)"
            )

        self._apply_selection(self._config.get("device", "gpu"))

        # D-Bus signal for device switching progress (reuses model switch pattern).
        self._dbus_client.subscribe_signal(
            "DeviceSwitchProgress", self._on_switch_progress
        )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _apply_selection(self, device: str) -> None:
        self._gpu_radio.selected = device == "gpu"
        self._cpu_radio.selected = device == "cpu"

    def _on_radio_clicked(self, device: str) -> None:
        if self._switching:
            return

        self._previous_device = self._config.get("device", "cpu")
        self._config["device"] = device
        self._apply_selection(device)
        self._on_changed()

        # Async device switch.
        self._switching = True
        active_radio = self._gpu_radio if device == "gpu" else self._cpu_radio
        other_radio = self._cpu_radio if device == "gpu" else self._gpu_radio
        active_radio.show_spinner()
        other_radio.disabled = True

        params = GLib.Variant("(s)", (device,))
        self._dbus_client._call_async(
            "SwitchDevice", parameters=params, callback=self._on_switch_result
        )
        # Safety timeout in case the service crashes mid-switch.
        self._switch_timeout_id = GLib.timeout_add(65000, self._on_switch_timeout)

    def _on_switch_result(self, result) -> None:
        if self._switch_timeout_id is not None:
            GLib.source_remove(self._switch_timeout_id)
            self._switch_timeout_id = None
        self._switching = False
        if result is not None:
            current = self._config.get("device", "cpu")
            radio = self._gpu_radio if current == "gpu" else self._cpu_radio
            radio.show_checkmark(2000)
        else:
            self._revert_device()

        if self._restore_timeout_id is not None:
            GLib.source_remove(self._restore_timeout_id)
        self._restore_timeout_id = GLib.timeout_add(2000, self._restore_ui)

    def _on_switch_timeout(self) -> bool:
        self._switch_timeout_id = None
        if self._switching:
            logger.warning("Device switch timed out in settings UI.")
            self._switching = False
            self._revert_device()
            if self._restore_timeout_id is not None:
                GLib.source_remove(self._restore_timeout_id)
            self._restore_timeout_id = GLib.timeout_add(2000, self._restore_ui)
        return False

    def _revert_device(self) -> None:
        current = self._config.get("device", "cpu")
        radio = self._gpu_radio if current == "gpu" else self._cpu_radio
        radio.show_x_mark()
        if self._previous_device:
            self._config["device"] = self._previous_device
            self._apply_selection(self._previous_device)
            self._on_changed()

    def _on_switch_progress(self, conn, sender, path, iface, signal_name, params) -> None:
        pass

    def _restore_ui(self) -> bool:
        self._restore_timeout_id = None
        self._gpu_radio.disabled = not self._has_cuda
        self._cpu_radio.disabled = False
        self._gpu_radio._clear_status()
        self._cpu_radio._clear_status()
        return False

    # ------------------------------------------------------------------
    # Config interface
    # ------------------------------------------------------------------

    def collect_config(self, config: dict) -> None:
        config["device"] = self._config.get("device", "cpu")

    def apply_config(self, config: dict) -> None:
        self._config["device"] = config.get("device", "cpu")
        self._apply_selection(self._config["device"])

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("device.label", fallback="Device")
        )
