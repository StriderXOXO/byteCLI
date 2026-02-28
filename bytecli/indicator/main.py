"""
Entry point for the ByteCLI floating indicator process.

Launches a Gtk.Application that shows a small pill-shaped window at the
bottom-center of the screen.  The indicator reflects the service state
(idle / recording) and provides quick access to the voice-input history.
"""

from __future__ import annotations

import logging
import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import GLib, Gtk

from bytecli.constants import INDICATOR_PID_FILE
from bytecli.service.pid_manager import PidManager
from bytecli.shared.css_provider import load_css
from bytecli.shared.dbus_client import DBusClient
from bytecli.shared.logging_setup import setup_logging

logger = setup_logging("bytecli.indicator")


class IndicatorApp(Gtk.Application):
    """GTK 4 application for the floating dictation indicator."""

    def __init__(self) -> None:
        super().__init__(application_id="com.bytecli.Indicator")
        self._dbus_client = DBusClient()
        self._indicator_window = None

    def do_activate(self) -> None:
        # PID guard -- only one indicator per session.
        try:
            PidManager.check_and_write(INDICATOR_PID_FILE)
        except RuntimeError:
            logger.warning("Another indicator instance is already running. Exiting.")
            self.quit()
            return

        # Load the shared CSS stylesheet.
        load_css()

        # Connect to the service D-Bus interface.
        if not self._dbus_client.connect():
            logger.warning(
                "Could not connect to ByteCLI service D-Bus. "
                "Indicator will start but may not reflect service state."
            )

        # Subscribe to D-Bus signals.
        self._dbus_client.subscribe_signal("StatusChanged", self._on_status_changed)
        self._dbus_client.subscribe_signal("RecordingStarted", self._on_recording_started)
        self._dbus_client.subscribe_signal("RecordingStopped", self._on_recording_stopped)

        # Create the indicator window.
        from bytecli.indicator.window import IndicatorWindow

        self._indicator_window = IndicatorWindow(application=self, dbus_client=self._dbus_client)
        self._indicator_window.present()

        # Fetch initial status to set the correct state.
        self._fetch_initial_status()

    # ------------------------------------------------------------------
    # D-Bus signal handlers
    # ------------------------------------------------------------------

    def _on_status_changed(
        self, connection, sender, path, iface, signal_name, params
    ) -> None:
        """Show or hide the indicator based on the service state."""
        if params is None:
            return
        status = params.unpack()[0] if params.n_children() > 0 else str(params.unpack())
        status_upper = status.upper()

        if self._indicator_window is None:
            return

        if status_upper in ("RUNNING", "STOPPING", "RESTARTING"):
            self._indicator_window.set_visible(True)
        else:
            self._indicator_window.set_visible(False)

    def _on_recording_started(
        self, connection, sender, path, iface, signal_name, params
    ) -> None:
        if self._indicator_window is not None:
            self._indicator_window.set_state_recording()

    def _on_recording_stopped(
        self, connection, sender, path, iface, signal_name, params
    ) -> None:
        if self._indicator_window is not None:
            self._indicator_window.set_state_idle()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_initial_status(self) -> None:
        """Query the current service status and set the indicator accordingly."""
        status = self._dbus_client.get_status()
        if status is None:
            return
        status_upper = status.upper()
        if self._indicator_window is None:
            return
        if status_upper in ("RUNNING", "STOPPING", "RESTARTING"):
            self._indicator_window.set_visible(True)
        else:
            self._indicator_window.set_visible(False)


def main() -> None:
    app = IndicatorApp()

    # Ensure clean shutdown on SIGTERM / SIGINT.
    def _signal_handler(sig, frame):
        logger.info("Received signal %d, shutting down.", sig)
        app.quit()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Allow GLib to handle Unix signals inside the main loop.
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, app.quit)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, app.quit)

    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
