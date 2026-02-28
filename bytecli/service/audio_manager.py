"""
Audio capture and device management.

Uses ``sounddevice`` for recording (callback mode) and ``pulsectl`` for
device enumeration and hot-plug monitoring.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

import numpy as np

from bytecli.constants import AUDIO_BUFFER_FRAMES, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioManager:
    """Manages audio input devices and recording streams."""

    def __init__(self) -> None:
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        self._hotplug_thread: Optional[threading.Thread] = None
        self._hotplug_running = False
        self._pulse_hotplug = None  # pulsectl.Pulse instance for events

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def get_devices() -> List[Tuple[str, str]]:
        """Return available PulseAudio input sources (excluding monitors).

        Each entry is ``(device_id, human_readable_name)``.
        """
        import pulsectl

        devices: List[Tuple[str, str]] = []
        try:
            with pulsectl.Pulse("bytecli-enum") as pulse:
                for src in pulse.source_list():
                    # Skip monitor sources (loopbacks of output sinks).
                    if ".monitor" in src.name:
                        continue
                    devices.append((src.name, src.description or src.name))
        except pulsectl.PulseError as exc:
            logger.error("Failed to list audio devices: %s", exc)

        logger.debug("Audio devices found: %d", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self, device_id: Optional[str] = None) -> None:
        """Begin recording audio from *device_id* (or the default source).

        Audio is captured via a ``sounddevice.InputStream`` in callback mode
        at 16 kHz mono float32 with a buffer of 1024 frames.
        """
        import sounddevice as sd

        with self._lock:
            if self._recording:
                logger.warning("Already recording – ignoring start request.")
                return

            self._chunks = []
            self._recording = True

        device = device_id if device_id and device_id != "auto" else None

        def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            if status:
                logger.warning("Audio stream status: %s", status)
            with self._lock:
                if self._recording:
                    self._chunks.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="float32",
                blocksize=AUDIO_BUFFER_FRAMES,
                device=device,
                callback=_callback,
            )
            self._stream.start()
            logger.info(
                "Recording started (device=%s, rate=%d, channels=%d).",
                device or "default",
                AUDIO_SAMPLE_RATE,
                AUDIO_CHANNELS,
            )
        except Exception as exc:
            with self._lock:
                self._recording = False
            logger.error("Failed to start recording: %s", exc)
            raise

    def stop_recording(self) -> np.ndarray:
        """Stop the current recording and return the audio as a 1-D float32 array.

        Returns an empty array if nothing was captured.
        """
        with self._lock:
            self._recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error stopping audio stream: %s", exc)
            finally:
                self._stream = None

        with self._lock:
            chunks = self._chunks
            self._chunks = []

        if not chunks:
            logger.warning("No audio data captured.")
            return np.array([], dtype=np.float32)

        audio = np.concatenate(chunks, axis=0).flatten().astype(np.float32)
        duration = len(audio) / AUDIO_SAMPLE_RATE
        logger.info("Recording stopped: %.2f s, %d samples.", duration, len(audio))
        return audio

    # ------------------------------------------------------------------
    # Hot-plug monitoring
    # ------------------------------------------------------------------

    def start_hotplug_monitor(
        self, callback: Callable[[List[Tuple[str, str]]], None]
    ) -> None:
        """Subscribe to PulseAudio source add/remove events.

        *callback* is invoked with the updated device list whenever a
        source is added or removed.
        """
        self._hotplug_running = True
        self._hotplug_thread = threading.Thread(
            target=self._hotplug_loop,
            args=(callback,),
            daemon=True,
        )
        self._hotplug_thread.start()
        logger.info("Audio hot-plug monitor started.")

    def _hotplug_loop(
        self, callback: Callable[[List[Tuple[str, str]]], None]
    ) -> None:
        """Long-running loop that listens for PulseAudio events."""
        import pulsectl

        try:
            self._pulse_hotplug = pulsectl.Pulse("bytecli-hotplug")

            def _event_handler(ev):
                # We care about source (input) events.
                if ev.facility == "source" and ev.t in ("new", "remove", "change"):
                    logger.debug("PulseAudio event: %s %s", ev.t, ev.facility)
                    try:
                        devices = self.get_devices()
                        callback(devices)
                    except Exception as exc:
                        logger.error("Hot-plug callback error: %s", exc)
                # Returning (not raising) keeps the event loop running.

            self._pulse_hotplug.event_mask_set("source")
            self._pulse_hotplug.event_callback_set(_event_handler)

            while self._hotplug_running:
                # event_listen blocks until an event fires or until we
                # call event_listen_stop from another thread.
                self._pulse_hotplug.event_listen(timeout=2)

        except Exception as exc:
            if self._hotplug_running:
                logger.error("Hot-plug monitor crashed: %s", exc)
        finally:
            if self._pulse_hotplug is not None:
                try:
                    self._pulse_hotplug.close()
                except Exception:
                    pass
                self._pulse_hotplug = None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop all recording streams and the hot-plug monitor."""
        # Stop recording if active.
        with self._lock:
            was_recording = self._recording
            self._recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        # Stop hot-plug monitor.
        self._hotplug_running = False
        if self._pulse_hotplug is not None:
            try:
                self._pulse_hotplug.event_listen_stop()
            except Exception:
                pass

        if self._hotplug_thread is not None:
            self._hotplug_thread.join(timeout=3)
            self._hotplug_thread = None

        logger.info("AudioManager stopped.")
