"""
Asynchronous model / device switcher with debounce and rollback.

Runs the heavy unload-then-load cycle on a background thread and emits
D-Bus progress signals via a caller-supplied callback.
"""

from __future__ import annotations

import enum
import logging
import threading
from typing import Callable, Optional

from bytecli.constants import MODEL_SWITCH_TIMEOUT
from bytecli.service.whisper_engine import WhisperEngine

logger = logging.getLogger(__name__)


class ModelSwitchState(enum.Enum):
    IDLE = "IDLE"
    SWITCHING = "SWITCHING"


class ModelSwitcher:
    """Manages non-blocking model and device switches for the service."""

    def __init__(self, engine: WhisperEngine) -> None:
        self._engine = engine
        self._state = ModelSwitchState.IDLE
        self._lock = threading.Lock()
        self._timeout_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ModelSwitchState:
        return self._state

    @property
    def is_switching(self) -> bool:
        return self._state is ModelSwitchState.SWITCHING

    # ------------------------------------------------------------------
    # Public API – model switching
    # ------------------------------------------------------------------

    def switch_model(
        self,
        new_model: str,
        dbus_signal_callback: Callable[[str, str], None],
    ) -> bool:
        """Initiate an asynchronous model switch.

        *dbus_signal_callback(state, msg)* is invoked with
        ``("switching", "")``, ``("success", "")`` or
        ``("failed", error_msg)``.

        Returns ``False`` if a switch is already in progress (debounce).
        """
        with self._lock:
            if self._state is ModelSwitchState.SWITCHING:
                logger.warning(
                    "Model switch already in progress – ignoring request."
                )
                return False
            self._state = ModelSwitchState.SWITCHING

        old_model = self._engine.current_model
        old_device = self._engine.current_device or "cpu"

        dbus_signal_callback("switching", "")

        # Start the timeout watchdog.
        self._timeout_timer = threading.Timer(
            MODEL_SWITCH_TIMEOUT,
            self._on_timeout,
            args=(old_model, old_device, dbus_signal_callback),
        )
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

        thread = threading.Thread(
            target=self._do_switch_model,
            args=(new_model, old_model, old_device, dbus_signal_callback),
            daemon=True,
        )
        thread.start()
        return True

    # ------------------------------------------------------------------
    # Public API – device switching
    # ------------------------------------------------------------------

    def switch_device(
        self,
        new_device: str,
        dbus_signal_callback: Callable[[str, str], None],
    ) -> bool:
        """Initiate an asynchronous device switch (same pattern as model)."""
        with self._lock:
            if self._state is ModelSwitchState.SWITCHING:
                logger.warning(
                    "Device switch already in progress – ignoring request."
                )
                return False
            self._state = ModelSwitchState.SWITCHING

        old_model = self._engine.current_model or "small"
        old_device = self._engine.current_device or "cpu"

        dbus_signal_callback("switching", "")

        self._timeout_timer = threading.Timer(
            MODEL_SWITCH_TIMEOUT,
            self._on_timeout,
            args=(old_model, old_device, dbus_signal_callback),
        )
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

        thread = threading.Thread(
            target=self._do_switch_device,
            args=(new_device, old_model, old_device, dbus_signal_callback),
            daemon=True,
        )
        thread.start()
        return True

    # ------------------------------------------------------------------
    # Internal workers
    # ------------------------------------------------------------------

    def _do_switch_model(
        self,
        new_model: str,
        old_model: Optional[str],
        old_device: str,
        callback: Callable[[str, str], None],
    ) -> None:
        try:
            self._engine.unload_model()
            self._engine.load_model(new_model, old_device)
            self._finish(callback, "success", "")
        except Exception as exc:
            logger.error("Model switch to '%s' failed: %s", new_model, exc)
            self._rollback(old_model, old_device, callback, str(exc))

    def _do_switch_device(
        self,
        new_device: str,
        old_model: str,
        old_device: str,
        callback: Callable[[str, str], None],
    ) -> None:
        try:
            self._engine.unload_model()
            self._engine.load_model(old_model, new_device)
            self._finish(callback, "success", "")
        except Exception as exc:
            logger.error("Device switch to '%s' failed: %s", new_device, exc)
            self._rollback(old_model, old_device, callback, str(exc))

    def _rollback(
        self,
        model: Optional[str],
        device: str,
        callback: Callable[[str, str], None],
        error_msg: str,
    ) -> None:
        """Attempt to reload the previous model after a failed switch."""
        if model is not None:
            try:
                self._engine.load_model(model, device)
                logger.info("Rolled back to model='%s' device='%s'.", model, device)
            except Exception as rb_exc:
                logger.critical(
                    "Rollback failed – service has no loaded model! %s", rb_exc
                )
        self._finish(callback, "failed", error_msg)

    def _finish(
        self,
        callback: Callable[[str, str], None],
        state: str,
        msg: str,
    ) -> None:
        """Cancel the timeout watchdog and reset internal state."""
        timer = self._timeout_timer
        if timer is not None:
            timer.cancel()
            self._timeout_timer = None

        with self._lock:
            if self._state is ModelSwitchState.IDLE:
                return  # Already finished (timeout/worker race).
            self._state = ModelSwitchState.IDLE

        try:
            callback(state, msg)
        except Exception:
            logger.exception("D-Bus signal callback raised an exception.")

    def _on_timeout(
        self,
        old_model: Optional[str],
        old_device: str,
        callback: Callable[[str, str], None],
    ) -> None:
        """Called by the Timer if the switch exceeds the deadline."""
        logger.error("Model/device switch timed out after %d s.", MODEL_SWITCH_TIMEOUT)
        # Attempt a rollback.
        self._rollback(old_model, old_device, callback, "Switch timed out.")
