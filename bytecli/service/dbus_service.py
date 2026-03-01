"""
D-Bus service object for ByteCLI.

Exposes the ``com.bytecli.ServiceInterface`` with all 11 methods and 6
signals defined in PRD section 2.3.  Each method delegates to the
appropriate manager injected at construction time.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, List, Tuple

import dbus
import dbus.service

from bytecli.constants import DBUS_BUS_NAME, DBUS_INTERFACE, DBUS_OBJECT_PATH

if TYPE_CHECKING:
    from bytecli.service.audio_manager import AudioManager
    from bytecli.service.config_manager import ConfigManager
    from bytecli.service.history_manager import HistoryManager
    from bytecli.service.hotkey_manager import HotkeyManager
    from bytecli.service.model_switcher import ModelSwitcher
    from bytecli.service.state_machine import ServiceStateMachine
    from bytecli.service.whisper_engine import WhisperEngine

logger = logging.getLogger(__name__)


class ByteCLIDBusService(dbus.service.Object):
    """Session-bus service object for ``com.bytecli.ServiceInterface``."""

    def __init__(
        self,
        bus_name: dbus.service.BusName,
        config_manager: "ConfigManager",
        state_machine: "ServiceStateMachine",
        whisper_engine: "WhisperEngine",
        audio_manager: "AudioManager",
        hotkey_manager: "HotkeyManager",
        history_manager: "HistoryManager",
        model_switcher: "ModelSwitcher",
    ) -> None:
        super().__init__(bus_name, DBUS_OBJECT_PATH)
        self._config = config_manager
        self._state = state_machine
        self._engine = whisper_engine
        self._audio = audio_manager
        self._hotkey = hotkey_manager
        self._history = history_manager
        self._switcher = model_switcher

        # Will be set by main.py after the recording FSM is created.
        self._indicator_restart_callback = None
        self._stop_callback = None
        self._restart_callback = None

    # ------------------------------------------------------------------
    # Setter for deferred dependencies
    # ------------------------------------------------------------------

    def set_indicator_restart_callback(self, cb):
        self._indicator_restart_callback = cb

    def set_stop_callback(self, cb):
        self._stop_callback = cb

    def set_restart_callback(self, cb):
        self._restart_callback = cb

    # ==================================================================
    # D-Bus METHODS
    # ==================================================================

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="s"
    )
    def GetStatus(self) -> str:
        """Return the current service state as a string."""
        return self._state.state.value

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="b"
    )
    def Stop(self) -> bool:
        """Request the service to shut down."""
        logger.info("D-Bus Stop() called.")
        if self._stop_callback is not None:
            try:
                self._stop_callback()
                return True
            except Exception as exc:
                logger.error("Stop callback failed: %s", exc)
                return False
        return False

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="b"
    )
    def Restart(self) -> bool:
        """Request the service to restart."""
        logger.info("D-Bus Restart() called.")
        if self._restart_callback is not None:
            try:
                self._restart_callback()
                return True
            except Exception as exc:
                logger.error("Restart callback failed: %s", exc)
                return False
        return False

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="b"
    )
    def RefreshIndicator(self) -> bool:
        """Kill and restart the indicator widget process."""
        logger.info("D-Bus RefreshIndicator() called.")
        if self._indicator_restart_callback is not None:
            try:
                self._indicator_restart_callback()
                return True
            except Exception as exc:
                logger.error("RefreshIndicator callback failed: %s", exc)
                return False
        return False

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="s", out_signature="b"
    )
    def SwitchModel(self, model: str) -> bool:
        """Initiate an asynchronous model switch."""
        logger.info("D-Bus SwitchModel(%r) called.", model)
        return self._switcher.switch_model(
            model,
            dbus_signal_callback=self.ModelSwitchProgress,
        )

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="s", out_signature="b"
    )
    def SwitchDevice(self, device: str) -> bool:
        """Initiate an asynchronous compute-device switch."""
        logger.info("D-Bus SwitchDevice(%r) called.", device)
        return self._switcher.switch_device(
            device,
            dbus_signal_callback=self.DeviceSwitchProgress,
        )

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="a(sss)"
    )
    def GetHistory(self) -> List[Tuple[str, str, str]]:
        """Return all transcription history entries."""
        return self._history.get_all()

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="a(ss)"
    )
    def GetAudioDevices(self) -> List[Tuple[str, str]]:
        """Return available audio input devices."""
        try:
            return self._audio.get_devices()
        except Exception as exc:
            logger.error("GetAudioDevices failed: %s", exc)
            return []

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="", out_signature="s"
    )
    def GetConfig(self) -> str:
        """Return the current configuration as a JSON string."""
        return json.dumps(self._config.config, ensure_ascii=False)

    @dbus.service.method(
        DBUS_INTERFACE, in_signature="s", out_signature="b"
    )
    def SaveConfig(self, config_json: str) -> bool:
        """Validate and persist a new configuration.

        Returns ``True`` on success.
        """
        logger.info("D-Bus SaveConfig() called.")
        try:
            new_config = json.loads(config_json)
        except json.JSONDecodeError as exc:
            logger.error("SaveConfig: invalid JSON: %s", exc)
            return False

        errors = self._config.validate(new_config)
        if errors:
            logger.warning("SaveConfig: validation errors: %s", errors)
            return False

        try:
            self._config.save(new_config)
            return True
        except Exception as exc:
            logger.error("SaveConfig: failed to save: %s", exc)
            return False

    # ==================================================================
    # D-Bus SIGNALS
    # ==================================================================

    @dbus.service.signal(DBUS_INTERFACE, signature="s")
    def StatusChanged(self, status: str) -> None:
        """Emitted when the service state changes."""
        logger.debug("Signal StatusChanged(%r)", status)

    @dbus.service.signal(DBUS_INTERFACE, signature="ss")
    def ModelSwitchProgress(self, state: str, msg: str) -> None:
        """Emitted during a model switch (switching/success/failed)."""
        logger.debug("Signal ModelSwitchProgress(%r, %r)", state, msg)

    @dbus.service.signal(DBUS_INTERFACE, signature="ss")
    def DeviceSwitchProgress(self, state: str, msg: str) -> None:
        """Emitted during a device switch (switching/success/failed)."""
        logger.debug("Signal DeviceSwitchProgress(%r, %r)", state, msg)

    @dbus.service.signal(DBUS_INTERFACE, signature="")
    def RecordingStarted(self) -> None:
        """Emitted when the user presses the hotkey and recording begins."""
        logger.debug("Signal RecordingStarted()")

    @dbus.service.signal(DBUS_INTERFACE, signature="s")
    def RecordingStopped(self, text: str) -> None:
        """Emitted when recording ends.  *text* is the transcription result."""
        logger.debug("Signal RecordingStopped(%r)", text[:80] if text else "")

    @dbus.service.signal(DBUS_INTERFACE, signature="a(ss)")
    def AudioDeviceChanged(self, devices: List[Tuple[str, str]]) -> None:
        """Emitted when PulseAudio sources are added or removed."""
        logger.debug("Signal AudioDeviceChanged(%d devices)", len(devices))
