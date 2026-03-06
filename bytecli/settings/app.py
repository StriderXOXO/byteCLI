"""
ByteCLISettingsApp -- GTK 3 Application for the settings panel.

Applies dark theme via CSS and loads the shared CSS stylesheet
before presenting the main SettingsWindow.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gio, Gtk

from bytecli.shared.css_provider import load_css
from bytecli.shared.logging_setup import setup_logging

logger = setup_logging("bytecli.settings")


class ByteCLISettingsApp(Gtk.Application):
    """Single-instance GTK 3 application for the ByteCLI settings panel."""

    def __init__(self) -> None:
        super().__init__(
            application_id="com.bytecli.Settings",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self) -> None:
        # Dark theme is applied entirely via CSS (bytecli.css).
        # Load shared CSS.
        load_css()

        # Present the window (re-use existing if already created).
        win = self.get_active_window()
        if win is None:
            from bytecli.settings.window import SettingsWindow

            win = SettingsWindow(application=self)
        win.show_all()
        win.present()
