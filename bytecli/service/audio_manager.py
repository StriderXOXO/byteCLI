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
        self._reader_thread: Optional[threading.Thread] = None
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
    # Device resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_device(device_id: Optional[str]):
        """Translate a PulseAudio source name to a usable sounddevice device.

        When the user selects a specific PulseAudio source, we set it as
        the PulseAudio default source via ``pactl`` and then record through
        the ``pulse`` PortAudio host API device.  This allows PulseAudio to
        handle sample-rate conversion (ALSA ``hw:`` devices often reject
        16 kHz directly).

        Returns ``None`` (system default) when *device_id* is ``None``,
        empty, or ``"auto"``.
        """
        if not device_id or device_id == "auto":
            return None

        # Set the chosen source as PulseAudio's default so "pulse" picks it up.
        try:
            import subprocess

            subprocess.check_call(
                ["pactl", "set-default-source", device_id],
                timeout=5,
            )
            logger.info("Set PA default source → '%s'", device_id)
        except Exception as exc:
            logger.warning(
                "pactl set-default-source failed for '%s': %s — using default",
                device_id,
                exc,
            )
            return None

        # Find the PulseAudio device in sounddevice's list.
        try:
            import sounddevice as sd

            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) > 0:
                    name = info.get("name", "")
                    if name == "pulse" or name == "default":
                        logger.info(
                            "Using sounddevice [%d] '%s' for PA source '%s'",
                            idx,
                            name,
                            device_id,
                        )
                        return idx
        except Exception as exc:
            logger.warning("sounddevice query failed: %s", exc)

        # Fallback: system default.
        return None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self, device_id: Optional[str] = None) -> None:
        """Begin recording audio from *device_id* (or the default source).

        *device_id* may be a PulseAudio source name (as returned by
        ``get_devices``) or ``"auto"`` / ``None`` for the system default.

        Audio is captured via a ``sounddevice.InputStream`` in blocking-read
        mode (no cffi callback) at 16 kHz mono float32.  A background thread
        pulls data from the stream to avoid cffi closure issues with
        mismatched libffi versions in some environments.
        """
        import sounddevice as sd

        with self._lock:
            if self._recording:
                logger.warning("Already recording – ignoring start request.")
                return

            self._chunks = []
            self._recording = True

        # Resolve the PulseAudio source name → sounddevice device index.
        device = self._resolve_device(device_id)

        try:
            # Open stream WITHOUT callback to avoid cffi ffi_prep_closure issues.
            self._stream = sd.InputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="float32",
                blocksize=AUDIO_BUFFER_FRAMES,
                device=device,
            )
            self._stream.start()
            logger.info(
                "Recording started (device=%s, rate=%d, channels=%d).",
                device if device is not None else "default",
                AUDIO_SAMPLE_RATE,
                AUDIO_CHANNELS,
            )
        except Exception as exc:
            with self._lock:
                self._recording = False
            logger.error("Failed to start recording: %s", exc)
            raise

        # Start a reader thread that polls the stream for data.
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="audio-reader",
        )
        self._reader_thread.start()

    def _read_loop(self) -> None:
        """Pull audio data from the open InputStream in a tight loop.

        The loop exits when ``_recording`` is set to ``False`` or the
        stream is stopped/closed from the main thread.  We deliberately
        catch *all* exceptions from ``stream.read()`` so that a stream
        abort (triggered by ``stop()``) exits cleanly without corrupting
        the heap.
        """
        try:
            while True:
                with self._lock:
                    if not self._recording:
                        break
                    stream = self._stream
                if stream is None or not stream.active:
                    break
                try:
                    data, overflowed = stream.read(AUDIO_BUFFER_FRAMES)
                    if overflowed:
                        logger.warning("Audio buffer overflowed.")
                    with self._lock:
                        if self._recording:
                            self._chunks.append(data.copy())
                except Exception:
                    # stream.read() will raise once the stream is stopped —
                    # this is the normal exit path.
                    break
        except Exception as exc:
            logger.warning("Audio reader thread error: %s", exc)

    def stop_recording(self) -> np.ndarray:
        """Stop the current recording and return the audio as a 1-D float32 array.

        Thread-safe shutdown order:
        1. Set ``_recording = False`` (signals reader thread to stop).
        2. Call ``stream.stop()`` (unblocks the blocking ``read()``).
        3. **Join** the reader thread to ensure it has exited.
        4. Call ``stream.close()`` (safe now — no other thread uses it).
        5. Collect and return the audio chunks.

        Returns an empty array if nothing was captured.
        """
        with self._lock:
            self._recording = False

        stream = self._stream

        # Step 2: stop the stream — this unblocks stream.read() in the
        # reader thread, causing it to raise or return empty data.
        if stream is not None:
            try:
                stream.stop()
            except Exception as exc:
                logger.warning("Error stopping audio stream: %s", exc)

        # Step 3: wait for the reader thread to finish.
        if self._reader_thread is not None:
            try:
                self._reader_thread.join(timeout=3)
            except Exception:
                pass
            self._reader_thread = None

        # Step 4: close the stream (reader is guaranteed to have exited).
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                logger.warning("Error closing audio stream: %s", exc)
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
