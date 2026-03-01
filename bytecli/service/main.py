"""
Entry point for the ByteCLI service daemon (``bytecli-service``).

Initialises all managers, registers the D-Bus service object, loads the
Whisper model, registers the global hotkey, and enters the GLib main loop.
Handles SIGTERM/SIGINT for graceful shutdown.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import logging
from typing import Optional

from bytecli.constants import (
    DBUS_BUS_NAME,
    INDICATOR_PID_FILE,
    PID_FILE,
)
from bytecli.shared.logging_setup import setup_logging


logger: Optional[logging.Logger] = None


def main() -> None:
    """Service daemon entry point."""
    global logger

    # ------------------------------------------------------------------
    # 1. Setup logging
    # ------------------------------------------------------------------
    logger = setup_logging("bytecli.service")
    logger.info("ByteCLI service starting (pid=%d).", os.getpid())

    # ------------------------------------------------------------------
    # 2. Check PID file -- ensure single-instance
    # ------------------------------------------------------------------
    from bytecli.service.pid_manager import PidManager

    try:
        PidManager.check_and_write(PID_FILE)
    except RuntimeError as exc:
        logger.error("Cannot start: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Load config
    # ------------------------------------------------------------------
    from bytecli.service.config_manager import ConfigManager

    config_manager = ConfigManager()
    config = config_manager.load()
    logger.info(
        "Configuration loaded: model=%s, device=%s",
        config["model"],
        config["device"],
    )

    # ------------------------------------------------------------------
    # 4. Init D-Bus / GLib main-loop integration
    # ------------------------------------------------------------------
    import dbus
    import dbus.mainloop.glib
    import dbus.service
    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    # ------------------------------------------------------------------
    # 5. Create session bus and claim the well-known bus name
    # ------------------------------------------------------------------
    session_bus = dbus.SessionBus()

    try:
        bus_name = dbus.service.BusName(
            DBUS_BUS_NAME,
            session_bus,
            do_not_queue=True,
        )
    except dbus.exceptions.NameExistsException:
        logger.error(
            "D-Bus name '%s' already taken -- another instance is running.",
            DBUS_BUS_NAME,
        )
        PidManager.cleanup(PID_FILE)
        sys.exit(1)

    # ------------------------------------------------------------------
    # 6. Create ServiceStateMachine with on_state_change callback
    # ------------------------------------------------------------------
    from bytecli.service.state_machine import (
        ServiceStateMachine,
        ServiceState,
        ServiceEvent,
    )

    # Forward reference: dbus_service is created later but used inside
    # the callback closure.  A mutable container avoids stale bindings.
    _dbus_service_ref: list = [None]

    def _on_state_change(old: ServiceState, new: ServiceState) -> None:
        """Forward state changes to the D-Bus StatusChanged signal."""
        try:
            svc = _dbus_service_ref[0]
            if svc is not None:
                svc.StatusChanged(new.value)
        except Exception:
            pass

    state_machine = ServiceStateMachine(on_state_change=_on_state_change)

    # ------------------------------------------------------------------
    # 7. Dispatch EVT_START
    # ------------------------------------------------------------------
    state_machine.dispatch(ServiceEvent.EVT_START)

    # ------------------------------------------------------------------
    # 8 - 18. Create managers, wire up, dispatch init result
    # ------------------------------------------------------------------
    loop = GLib.MainLoop()

    try:
        # 8. Create WhisperEngine (model loading is deferred).
        from bytecli.service.whisper_engine import WhisperEngine

        whisper_engine = WhisperEngine()

        device = config.get("device", "cpu")
        if device == "gpu" and not WhisperEngine.is_cuda_available():
            logger.warning("CUDA not available -- falling back to CPU.")
            device = "cpu"
            cfg = config_manager.config
            cfg["device"] = "cpu"
            config_manager.save(cfg)

        # 9. Create AudioManager.
        from bytecli.service.audio_manager import AudioManager

        audio_manager = AudioManager()

        # 10. Create HotkeyManager.
        from bytecli.service.hotkey_manager import HotkeyManager

        hotkey_manager = HotkeyManager()

        # 11. Create HistoryManager and load().
        from bytecli.service.history_manager import HistoryManager

        history_manager = HistoryManager(
            max_entries=config.get("history_max_entries", 50),
        )
        history_manager.load()

        # 12. Create ModelSwitcher.
        from bytecli.service.model_switcher import ModelSwitcher

        model_switcher = ModelSwitcher(whisper_engine)

        # 13. Create ByteCLIDBusService with all managers.
        from bytecli.service.dbus_service import ByteCLIDBusService

        dbus_service = ByteCLIDBusService(
            bus_name=bus_name,
            config_manager=config_manager,
            state_machine=state_machine,
            whisper_engine=whisper_engine,
            audio_manager=audio_manager,
            hotkey_manager=hotkey_manager,
            history_manager=history_manager,
            model_switcher=model_switcher,
        )
        _dbus_service_ref[0] = dbus_service

        # 14. Create RecordingFSM and wire it up.
        from bytecli.service.recording_fsm import RecordingFSM

        recording_fsm = RecordingFSM(
            audio_manager=audio_manager,
            whisper_engine=whisper_engine,
            history_manager=history_manager,
            dbus_recording_started_signal=dbus_service.RecordingStarted,
            dbus_recording_stopped_signal=dbus_service.RecordingStopped,
            config_manager=config_manager,
        )

        hotkey_manager.on_press(recording_fsm.on_hotkey_toggle)

        # 15. Register the fixed Ctrl+Alt+V hotkey.
        hotkey_keys = ["Ctrl", "Alt", "V"]
        try:
            hotkey_manager.register(hotkey_keys)
        except Exception as exc:
            logger.warning(
                "Failed to register hotkey %s: %s. "
                "Service will run but hotkey is unavailable.",
                hotkey_keys, exc,
            )

        # 16. Start audio hotplug monitor.
        def _on_devices_changed(devices):
            try:
                dbus_service.AudioDeviceChanged(devices)
            except Exception:
                pass

        audio_manager.start_hotplug_monitor(_on_devices_changed)

        # 17. Set callbacks on dbus_service (stop, restart, indicator).
        _shutting_down = False

        def _cleanup() -> None:
            """Release all resources held by the service."""
            try:
                recording_fsm.shutdown()
            except Exception as exc:
                logger.debug("RecordingFSM shutdown error: %s", exc)
            try:
                hotkey_manager.unregister()
            except Exception as exc:
                logger.debug("Hotkey unregister error: %s", exc)
            try:
                audio_manager.stop()
            except Exception as exc:
                logger.debug("AudioManager stop error: %s", exc)
            try:
                whisper_engine.unload_model()
            except Exception as exc:
                logger.debug("Model unload error: %s", exc)
            _kill_indicator()

        def _stop_service() -> None:
            """Graceful stop: dispatch EVT_STOP, cleanup, EVT_SHUTDOWN_DONE, quit."""
            nonlocal _shutting_down
            if _shutting_down:
                return
            _shutting_down = True
            state_machine.dispatch(ServiceEvent.EVT_STOP)
            _cleanup()
            state_machine.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE)
            loop.quit()

        def _restart_service() -> None:
            """Restart: dispatch EVT_RESTART, cleanup, EVT_SHUTDOWN_DONE, re-exec."""
            nonlocal _shutting_down
            if _shutting_down:
                return
            _shutting_down = True
            state_machine.dispatch(ServiceEvent.EVT_RESTART)
            _cleanup()
            state_machine.dispatch(ServiceEvent.EVT_SHUTDOWN_DONE)
            logger.info("Re-executing service for restart ...")
            loop.quit()
            os.execv(sys.executable, [sys.executable, "-m", "bytecli.service.main"])

        def _refresh_indicator() -> None:
            """Kill and restart the indicator process."""
            _kill_indicator()
            _start_indicator()

        dbus_service.set_stop_callback(_stop_service)
        dbus_service.set_restart_callback(_restart_service)
        dbus_service.set_indicator_restart_callback(_refresh_indicator)

        # 18. Dispatch EVT_INIT_SUCCESS *before* model loading so the
        #     indicator appears immediately and can show download progress.
        state_machine.dispatch(ServiceEvent.EVT_INIT_SUCCESS)
        logger.info("Service initialised -- entering main loop (model loading deferred).")

    except Exception as exc:
        logger.error("Service initialisation failed: %s", exc)
        state_machine.dispatch(ServiceEvent.EVT_INIT_FAIL)
        PidManager.cleanup(PID_FILE)
        sys.exit(1)

    # Start the indicator widget.
    _start_indicator()

    # ------------------------------------------------------------------
    # 19. Load Whisper model asynchronously with progress reporting
    # ------------------------------------------------------------------
    def _on_model_progress(percent: int, message: str) -> None:
        """Forward download progress to D-Bus (runs on background thread)."""
        try:
            GLib.idle_add(dbus_service.ModelDownloadProgress, percent, message)
        except Exception:
            pass

    def _on_model_done(success: bool, message: str) -> None:
        """Handle model loading completion (runs on background thread)."""
        def _notify_done():
            if success:
                logger.info("Whisper model loaded: %s", message)
                try:
                    dbus_service.ModelDownloadProgress(100, "Ready")
                except Exception:
                    pass
                _send_notification(
                    "ByteCLI is ready!",
                    "Press Ctrl+Alt+V to dictate.",
                )
            else:
                logger.error("Whisper model load failed: %s", message)
                try:
                    dbus_service.ModelDownloadProgress(-1, f"Failed: {message}")
                except Exception:
                    pass
                _send_notification(
                    "ByteCLI model load failed",
                    message,
                )
            return False
        GLib.idle_add(_notify_done)

    # Send a notification if this is a first-run download.
    if not whisper_engine._model_file_exists(config["model"]):
        model_info = {}
        from bytecli.constants import WHISPER_MODELS as _WM
        model_info = _WM.get(config["model"], {})
        size_str = model_info.get("size", "")
        _send_notification(
            "ByteCLI is downloading the speech model",
            f"Downloading {config['model']} model ({size_str}). This may take a few minutes.",
        )

    whisper_engine.load_model_async(
        config["model"],
        device,
        progress_callback=_on_model_progress,
        done_callback=_on_model_done,
    )

    # ------------------------------------------------------------------
    # 21. Signal handlers for graceful shutdown (SIGTERM / SIGINT)
    # ------------------------------------------------------------------
    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received %s -- shutting down.", sig_name)
        _stop_service()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # ------------------------------------------------------------------
    # 22. Run GLib.MainLoop
    # ------------------------------------------------------------------
    try:
        loop.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt -- shutting down.")
    finally:
        # Guard against double-cleanup; _stop_service may have already run.
        try:
            audio_manager.stop()
        except Exception:
            pass
        PidManager.cleanup(PID_FILE)
        logger.info("Service exited.")


# ======================================================================
# Helper functions
# ======================================================================

def _start_indicator() -> None:
    """Launch the indicator widget as a child process."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "bytecli.indicator.main"],
            start_new_session=True,
        )
        logger.info("Indicator process started.")
    except Exception as exc:
        logger.warning("Failed to start indicator: %s", exc)


def _kill_indicator() -> None:
    """Terminate the indicator widget via its PID file."""
    from bytecli.service.pid_manager import PidManager

    if not os.path.isfile(INDICATOR_PID_FILE):
        return

    try:
        with open(INDICATOR_PID_FILE, "r") as fh:
            pid = int(fh.read().strip())
        os.kill(pid, signal.SIGTERM)
        logger.info("Indicator process (pid=%d) terminated.", pid)
    except (OSError, ValueError) as exc:
        logger.debug("Could not kill indicator: %s", exc)
    finally:
        PidManager.cleanup(INDICATOR_PID_FILE)


def _send_notification(title: str, body: str) -> None:
    """Send a desktop notification via notify-send."""
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=ByteCLI", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        if logger:
            logger.debug("notify-send not available; skipping notification.")


if __name__ == "__main__":
    main()
