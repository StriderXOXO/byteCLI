"""
ByteCLISettingsApp -- Adw.Application for the settings panel.

Forces dark theme via Adw.StyleManager and loads the shared CSS
stylesheet before presenting the main SettingsWindow.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio

from bytecli.shared.css_provider import load_css
from bytecli.shared.logging_setup import setup_logging

logger = setup_logging("bytecli.settings")


class ByteCLISettingsApp(Adw.Application):
    """Single-instance Adw application for the ByteCLI settings panel."""

    def __init__(self) -> None:
        super().__init__(
            application_id="com.bytecli.Settings",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self) -> None:
        # Force dark colour scheme.
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        # Load shared CSS.
        load_css()

        # Present the window (re-use existing if already created).
        win = self.get_active_window()
        if win is None:
            from bytecli.settings.window import SettingsWindow

            win = SettingsWindow(application=self)
        win.present()
