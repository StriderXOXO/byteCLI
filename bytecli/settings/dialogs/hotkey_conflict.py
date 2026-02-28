"""
HotkeyConflictDialog -- modal warning when a hotkey combination
conflicts with an existing system binding.

Displays a semi-transparent overlay (#000000AA background) with a
centred 300px card containing:
    - Warning icon
    - "Hotkey Conflict Detected" title
    - Body explaining the conflict and revert
    - Full-width primary-orange pill-shaped OK button

Usage::

    dialog = HotkeyConflictDialog(
        parent=settings_window,
        keys="Ctrl + Alt + V",
        source="org.gnome.desktop.wm.keybindings switch-windows",
        prev_keys="Ctrl + Shift + V",
    )
    dialog.present()
"""

from __future__ import annotations

import logging
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from bytecli.i18n import i18n

logger = logging.getLogger(__name__)


class HotkeyConflictDialog(Gtk.Window):
    """Modal dialog for hotkey conflict notification.

    Parameters
    ----------
    parent:
        The transient parent window (typically the SettingsWindow).
        May be ``None`` if the root window is not available.
    keys:
        Human-readable representation of the conflicting hotkey
        (e.g. ``"Ctrl + Alt + V"``).
    source:
        Description of what already owns the binding
        (e.g. ``"org.gnome.desktop.wm.keybindings switch-windows"``).
    prev_keys:
        The hotkey we are reverting to (e.g. ``"Ctrl + Shift + V"``).
    """

    def __init__(
        self,
        *,
        parent: Optional[Gtk.Window] = None,
        keys: str,
        source: str,
        prev_keys: str,
    ) -> None:
        super().__init__()
        self.set_decorated(False)
        self.set_modal(True)
        self.set_resizable(False)
        self.set_default_size(360, -1)
        self.set_title("")

        if parent is not None and isinstance(parent, Gtk.Window):
            self.set_transient_for(parent)

        # Semi-transparent background overlay.
        self._apply_overlay_css()

        # Outer container centres the card.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_valign(Gtk.Align.CENTER)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_vexpand(True)

        # Card container.
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.set_size_request(300, -1)
        card.set_margin_start(24)
        card.set_margin_end(24)
        card.set_margin_top(24)
        card.set_margin_bottom(24)
        card.add_css_class("conflict-card")
        self._apply_card_css(card)

        # Warning icon.
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.set_pixel_size(32)
        icon.set_halign(Gtk.Align.CENTER)
        icon.add_css_class("text-warning")
        card.append(icon)

        # Title.
        title = Gtk.Label(
            label=i18n.t(
                "settings.hotkey.conflict_title",
                fallback="Hotkey Conflict Detected",
            )
        )
        title.add_css_class("mono")
        title.add_css_class("font-semibold")
        title.add_css_class("text-lg")
        title.set_halign(Gtk.Align.CENTER)
        card.append(title)

        # Body text.
        body_text = i18n.t(
            "settings.hotkey.conflict_body",
            keys=keys,
            source=source,
            prev=prev_keys,
            fallback=(
                f"The hotkey {keys} is already used by {source}. "
                f"Reverting to {prev_keys}."
            ),
        )
        body = Gtk.Label(label=body_text)
        body.add_css_class("text-muted")
        _apply_font_size(body, 13)
        body.set_wrap(True)
        body.set_max_width_chars(36)
        body.set_halign(Gtk.Align.CENTER)
        body.set_justify(Gtk.Justification.CENTER)
        body.set_size_request(252, -1)
        card.append(body)

        # OK button (full width, primary orange, pill shape).
        ok_btn = Gtk.Button(
            label=i18n.t("settings.hotkey.conflict_ok", fallback="OK")
        )
        ok_btn.add_css_class("primary-btn")
        ok_btn.add_css_class("mono")
        ok_btn.add_css_class("font-medium")
        ok_btn.set_hexpand(True)
        ok_btn.connect("clicked", self._on_ok)
        card.append(ok_btn)

        outer.append(card)
        self.set_child(outer)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_ok(self, btn) -> None:
        self.close()

    # ------------------------------------------------------------------
    # CSS
    # ------------------------------------------------------------------

    def _apply_overlay_css(self) -> None:
        provider = Gtk.CssProvider()
        css = "window { background-color: rgba(0, 0, 0, 0.67); }"
        provider.load_from_data(css.encode())
        self.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    @staticmethod
    def _apply_card_css(widget: Gtk.Widget) -> None:
        provider = Gtk.CssProvider()
        css = (
            ".conflict-card {"
            "  background-color: #1A1A1A;"
            "  border-radius: 12px;"
            "  border: 1px solid #2E2E2E;"
            "  padding: 24px;"
            "}"
        )
        provider.load_from_data(css.encode())
        widget.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def _apply_font_size(widget: Gtk.Widget, size_px: int) -> None:
    provider = Gtk.CssProvider()
    css = f"* {{ font-size: {size_px}px; }}"
    provider.load_from_data(css.encode())
    widget.get_style_context().add_provider(
        provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
