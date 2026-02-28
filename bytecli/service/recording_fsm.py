"""
Recording finite state machine.

Manages the IDLE -> RECORDING -> TRANSCRIBING lifecycle that is driven
by hotkey press / release events.  Short presses (< 0.3 s) are discarded as
accidental; recordings are capped at 300 s with an auto-stop.
"""

from __future__ import annotations

import enum
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable, Optional

from gi.repository import GLib

from bytecli.constants import MAX_RECORDING_DURATION, MIN_RECORDING_DURATION

if TYPE_CHECKING:
    from bytecli.service.audio_manager import AudioManager
    from bytecli.service.config_manager import ConfigManager
    from bytecli.service.history_manager import HistoryManager
    from bytecli.service.whisper_engine import WhisperEngine

logger = logging.getLogger(__name__)


class RecordingState(enum.Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"


class RecordingFSM:
    """State machine that bridges hotkey events with audio capture and
    Whisper transcription.

    Parameters
    ----------
    audio_manager:
        Manages audio input streams.
    whisper_engine:
        Loaded Whisper model wrapper.
    history_manager:
        Persists transcription entries.
    dbus_recording_started_signal:
        Callable (no args) that emits the ``RecordingStarted`` D-Bus signal.
    dbus_recording_stopped_signal:
        Callable accepting a single ``str`` argument that emits the
        ``RecordingStopped(text)`` D-Bus signal.
    config_manager:
        Used to read the current ``audio_input`` device identifier.
    """

    def __init__(
        self,
        audio_manager: "AudioManager",
        whisper_engine: "WhisperEngine",
        history_manager: "HistoryManager",
        dbus_recording_started_signal: Callable[[], None],
        dbus_recording_stopped_signal: Callable[[str], None],
        config_manager: "ConfigManager",
    ) -> None:
        self._audio = audio_manager
        self._engine = whisper_engine
        self._history = history_manager
        self._sig_started = dbus_recording_started_signal
        self._sig_stopped = dbus_recording_stopped_signal
        self._config = config_manager

        self._state = RecordingState.IDLE
        self._press_time: float = 0.0
        self._auto_stop_source_id: Optional[int] = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="transcribe")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> RecordingState:
        return self._state

    # ------------------------------------------------------------------
    # Hotkey callbacks (called from GLib main loop via idle_add)
    # ------------------------------------------------------------------

    def on_hotkey_toggle(self) -> None:
        """Handle a hotkey-press event in toggle mode.

        Each press toggles the recording state:
        - **IDLE → RECORDING**: begins audio capture, emits ``RecordingStarted``,
          starts the auto-stop safety timer.
        - **RECORDING → TRANSCRIBING**: stops capture, submits audio to Whisper.
          If the recording is shorter than ``MIN_RECORDING_DURATION`` it is
          discarded as an accidental double-tap.
        - **TRANSCRIBING**: ignored (transcription already in progress).
        """
        if self._state is RecordingState.IDLE:
            self._start_recording()
        elif self._state is RecordingState.RECORDING:
            self._stop_recording()
        else:
            logger.debug(
                "Hotkey toggle ignored -- current state is %s.", self._state.value
            )

    # ------------------------------------------------------------------
    # Start / stop helpers
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        """Begin audio capture (IDLE → RECORDING)."""
        self._press_time = time.monotonic()
        self._state = RecordingState.RECORDING

        # Resolve the audio device from config each time so hot-swaps
        # are picked up without restarting the service.
        device = self._config.config.get("audio_input", "auto")
        device_id = device if device and device != "auto" else None

        try:
            self._audio.start_recording(device_id)
        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            self._state = RecordingState.IDLE
            return

        # Emit D-Bus signal.
        try:
            self._sig_started()
        except Exception:
            logger.debug("RecordingStarted signal emission failed.", exc_info=True)

        # Schedule auto-stop after MAX_RECORDING_DURATION seconds.
        self._auto_stop_source_id = GLib.timeout_add(
            int(MAX_RECORDING_DURATION * 1000),
            self._auto_stop,
        )

        logger.info("Recording started (device=%s).", device_id or "default")

    def _stop_recording(self) -> None:
        """Stop audio capture and submit for transcription (RECORDING → TRANSCRIBING).

        If the recording is shorter than ``MIN_RECORDING_DURATION`` seconds
        it is discarded as an accidental double-tap.
        """
        duration = time.monotonic() - self._press_time

        # Cancel auto-stop timer.
        self._cancel_auto_stop()

        if duration < MIN_RECORDING_DURATION:
            logger.info(
                "Recording too short (%.2f s < %.2f s) -- discarding.",
                duration,
                MIN_RECORDING_DURATION,
            )
            try:
                self._audio.stop_recording()
            except Exception:
                pass
            self._state = RecordingState.IDLE
            return

        # Stop capture and retrieve the audio buffer.
        try:
            audio_data = self._audio.stop_recording()
        except Exception as exc:
            logger.error("Error stopping recording: %s", exc)
            self._state = RecordingState.IDLE
            return

        if audio_data.size == 0:
            logger.warning("Empty audio buffer -- nothing to transcribe.")
            self._state = RecordingState.IDLE
            self._emit_stopped("")
            return

        self._state = RecordingState.TRANSCRIBING
        duration_ms = int(duration * 1000)

        logger.info(
            "Recording stopped (%.2f s). Submitting for transcription.", duration
        )

        self._pool.submit(self._do_transcribe, audio_data, duration_ms)

    # ------------------------------------------------------------------
    # Transcription (runs on thread-pool thread)
    # ------------------------------------------------------------------

    def _do_transcribe(self, audio_data, duration_ms: int) -> None:
        """Run Whisper transcription and deliver the result on the main loop."""
        try:
            text = self._engine.transcribe(audio_data)
        except Exception as exc:
            logger.error("Transcription error: %s", exc)
            GLib.idle_add(self._on_transcription_error, str(exc))
            return

        if not text:
            logger.info("No speech detected.")
            GLib.idle_add(self._on_no_speech)
            return

        # Deliver the result on the main loop.
        GLib.idle_add(self._on_transcription_done, text, duration_ms)

    def _on_transcription_done(self, text: str, duration_ms: int) -> bool:
        """Called on the GLib main loop after successful transcription."""
        from bytecli.service.text_output import type_text

        logger.info("Transcription result (%d ms): %s", duration_ms, text[:100])

        # Type the text at the cursor.
        success, fallback = type_text(text)
        if not success:
            logger.error("Failed to deliver text to focused window.")
        elif fallback:
            logger.info("Text delivered via clipboard fallback.")

        # Persist to history.
        model = self._engine.current_model or "unknown"
        self._history.add(text, model, duration_ms)

        # Emit D-Bus signal.
        self._emit_stopped(text)

        self._state = RecordingState.IDLE
        return False  # remove idle source

    def _on_no_speech(self) -> bool:
        """Called when the engine returned empty text."""
        self._emit_stopped("")
        self._state = RecordingState.IDLE
        return False

    def _on_transcription_error(self, error_msg: str) -> bool:
        """Called when transcription raised an exception."""
        self._emit_stopped("")
        self._state = RecordingState.IDLE
        return False

    # ------------------------------------------------------------------
    # Auto-stop
    # ------------------------------------------------------------------

    def _auto_stop(self) -> bool:
        """GLib timeout callback: stop recording at MAX_RECORDING_DURATION."""
        if self._state is not RecordingState.RECORDING:
            return False

        logger.warning(
            "Maximum recording duration reached (%.0f s) -- auto-stopping.",
            MAX_RECORDING_DURATION,
        )

        self._auto_stop_source_id = None
        # Reuse the normal stop path.
        self._stop_recording()
        return False  # do not repeat

    def _cancel_auto_stop(self) -> None:
        """Remove the pending auto-stop timer, if any."""
        if self._auto_stop_source_id is not None:
            GLib.source_remove(self._auto_stop_source_id)
            self._auto_stop_source_id = None

    # ------------------------------------------------------------------
    # D-Bus signal helpers
    # ------------------------------------------------------------------

    def _emit_stopped(self, text: str) -> None:
        """Safely emit the RecordingStopped signal."""
        try:
            self._sig_stopped(text)
        except Exception:
            logger.debug("RecordingStopped signal emission failed.", exc_info=True)
