"""
ServerStatusSection -- displays the ByteCLI service lifecycle state and
provides Start / Stop / Restart controls.

Also includes a "Refresh Indicator" button for recovering a lost
floating indicator.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard
from bytecli.settings.widgets.styled_button import StyledButton

logger = logging.getLogger(__name__)

# Visual mapping: state -> (dot_css_class, colour_hex)
_STATE_DOT_CLASS = {
    "RUNNING": "status-dot-running",
    "STOPPED": "status-dot-stopped",
    "STARTING": "status-dot-starting",
    "STOPPING": "status-dot-stopping",
    "RESTARTING": "status-dot-restarting",
    "FAILED": "status-dot-failed",
}


class ServerStatusSection(Gtk.Box):
    """Displays the service state with action buttons."""

    def __init__(self, dbus_client: DBusClient) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._dbus_client = dbus_client
        self._current_state = "STOPPED"
        self._model_name = ""

        self._card = SectionCard(
            title=i18n.t("settings.server_status.title", fallback="Server Status")
        )

        # --- Top row: dot + status text + action buttons -----------------
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top_row.set_valign(Gtk.Align.CENTER)

        # Status dot.
        self._dot = Gtk.DrawingArea()
        self._dot.set_size_request(8, 8)
        self._dot.set_valign(Gtk.Align.CENTER)
        self._dot.set_draw_func(self._draw_dot)
        top_row.append(self._dot)

        # Status text.
        self._status_label = Gtk.Label(label=i18n.t("server.stopped", fallback="Stopped"))
        self._status_label.add_css_class("text-base")
        self._status_label.add_css_class("font-medium")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)
        top_row.append(self._status_label)

        # Action buttons.
        self._btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._stop_btn = StyledButton(
            label=i18n.t("settings.server_status.stop", fallback="Stop"),
            variant="secondary",
        )
        self._stop_btn.add_css_class("btn-sm")
        self._stop_btn.connect("clicked", self._on_stop)
        self._btn_box.append(self._stop_btn)

        self._restart_btn = StyledButton(
            label=i18n.t("settings.server_status.restart", fallback="Restart"),
            variant="secondary",
        )
        self._restart_btn.add_css_class("btn-sm")
        self._restart_btn.connect("clicked", self._on_restart)
        self._btn_box.append(self._restart_btn)

        self._start_btn = StyledButton(
            label=i18n.t("settings.server_status.start", fallback="Start"),
            variant="primary",
        )
        self._start_btn.add_css_class("btn-sm")
        self._start_btn.connect("clicked", self._on_start)
        self._btn_box.append(self._start_btn)

        top_row.append(self._btn_box)
        self._card.card_content.append(top_row)

        # --- Error detail (hidden by default) ----------------------------
        self._error_label = Gtk.Label()
        self._error_label.add_css_class("text-error")
        self._error_label.add_css_class("text-sm")
        self._error_label.set_halign(Gtk.Align.START)
        self._error_label.set_wrap(True)
        self._error_label.set_visible(False)
        self._card.card_content.append(self._error_label)

        # Separator.
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        self._card.card_content.append(sep)

        # --- Bottom row: refresh indicator -------------------------------
        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        hint = Gtk.Label(
            label=i18n.t(
                "settings.server_status.indicator_hint",
                fallback="Floating indicator disappeared?",
            )
        )
        hint.add_css_class("text-muted")
        hint.add_css_class("text-sm")
        hint.set_halign(Gtk.Align.START)
        hint.set_hexpand(True)
        bottom_row.append(hint)

        self._refresh_btn = StyledButton(
            label=i18n.t(
                "settings.server_status.refresh_indicator",
                fallback="Refresh Indicator",
            ),
            variant="secondary",
        )
        self._refresh_btn.add_css_class("btn-sm")
        self._refresh_btn.connect("clicked", self._on_refresh_indicator)
        bottom_row.append(self._refresh_btn)

        self._card.card_content.append(bottom_row)

        self.append(self._card)

        # Subscribe to StatusChanged signal.
        self._dbus_client.subscribe_signal("StatusChanged", self._on_status_signal)

        # Fetch initial status.
        self._fetch_status()

    # ------------------------------------------------------------------
    # State rendering
    # ------------------------------------------------------------------

    def _set_state(self, state: str, model: str = "", error: str = "") -> None:
        self._current_state = state.upper()
        self._model_name = model
        self._dot.queue_draw()

        if self._current_state == "RUNNING":
            display = i18n.t("server.running", model=model, fallback=f"Running ({model})")
            self._status_label.set_text(display)
            self._stop_btn.set_visible(True)
            self._stop_btn.set_disabled(False)
            self._restart_btn.set_visible(True)
            self._restart_btn.set_disabled(False)
            self._start_btn.set_visible(False)
            self._error_label.set_visible(False)

        elif self._current_state == "STOPPING":
            self._status_label.set_text(
                i18n.t("server.stopping", fallback="Stopping...")
            )
            self._stop_btn.set_visible(True)
            self._stop_btn.set_disabled(True)
            self._restart_btn.set_visible(True)
            self._restart_btn.set_disabled(True)
            self._start_btn.set_visible(False)
            self._error_label.set_visible(False)

        elif self._current_state == "STOPPED":
            self._status_label.set_text(
                i18n.t("server.stopped", fallback="Stopped")
            )
            self._stop_btn.set_visible(False)
            self._restart_btn.set_visible(False)
            self._start_btn.set_visible(True)
            self._start_btn.set_disabled(False)
            self._error_label.set_visible(False)

        elif self._current_state == "STARTING":
            self._status_label.set_text(
                i18n.t("server.starting", fallback="Starting...")
            )
            self._stop_btn.set_visible(False)
            self._restart_btn.set_visible(False)
            self._start_btn.set_visible(True)
            self._start_btn.set_disabled(True)
            self._error_label.set_visible(False)

        elif self._current_state == "RESTARTING":
            self._status_label.set_text(
                i18n.t("server.restarting", fallback="Restarting...")
            )
            self._stop_btn.set_visible(True)
            self._stop_btn.set_disabled(True)
            self._restart_btn.set_visible(True)
            self._restart_btn.set_disabled(True)
            self._start_btn.set_visible(False)
            self._error_label.set_visible(False)

        elif self._current_state == "FAILED":
            self._status_label.set_text(
                i18n.t("server.failed", fallback="Failed")
            )
            self._stop_btn.set_visible(False)
            self._restart_btn.set_visible(True)
            self._restart_btn.set_disabled(False)
            self._start_btn.set_visible(False)
            if error:
                self._error_label.set_text(error)
                self._error_label.set_visible(True)

    # ------------------------------------------------------------------
    # Dot drawing
    # ------------------------------------------------------------------

    def _draw_dot(self, area, cr, width, height) -> None:
        colours = {
            "RUNNING": (0.714, 1.0, 0.808),
            "STOPPED": (1.0, 0.36, 0.2),
            "STARTING": (1.0, 0.518, 0.0),
            "STOPPING": (1.0, 0.518, 0.0),
            "RESTARTING": (1.0, 0.518, 0.0),
            "FAILED": (1.0, 0.36, 0.2),
        }
        r, g, b = colours.get(self._current_state, (0.722, 0.725, 0.714))
        cr.set_source_rgba(r, g, b, 1.0)
        radius = min(width, height) / 2.0
        cr.arc(width / 2.0, height / 2.0, radius, 0, 2 * math.pi)
        cr.fill()

    # ------------------------------------------------------------------
    # D-Bus interactions
    # ------------------------------------------------------------------

    def _fetch_status(self) -> None:
        status = self._dbus_client.get_status()
        if status is not None:
            # Status may be "RUNNING" or "RUNNING:small" etc.
            parts = status.split(":", 1)
            state = parts[0].upper()
            model = parts[1] if len(parts) > 1 else ""
            self._set_state(state, model=model)

    def _on_status_signal(self, conn, sender, path, iface, signal_name, params) -> None:
        if params is None:
            return
        raw = params.unpack()[0] if params.n_children() > 0 else str(params.unpack())
        parts = raw.split(":", 1)
        state = parts[0].upper()
        model = parts[1] if len(parts) > 1 else ""
        error = parts[1] if len(parts) > 1 and state == "FAILED" else ""
        self._set_state(state, model=model, error=error)

    def _on_start(self, btn) -> None:
        self._set_state("STARTING")
        self._dbus_client.start_service()

    def _on_stop(self, btn) -> None:
        self._set_state("STOPPING")
        self._dbus_client.stop_service()

    def _on_restart(self, btn) -> None:
        self._set_state("RESTARTING")
        self._dbus_client.restart_service()

    def _on_refresh_indicator(self, btn) -> None:
        self._dbus_client.refresh_indicator()

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("settings.server_status.title", fallback="Server Status")
        )
        # Re-render the current state to refresh status text.
        self._set_state(self._current_state, model=self._model_name)
