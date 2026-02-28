"""
StyledButton -- pill-shaped button with primary / secondary / destructive variants.

Matches the ByteCLI design system:
- Primary:     bg #FF8400, text #111111
- Secondary:   bg #111111, border 1px #2E2E2E, text #FFFFFF
- Destructive: bg #FF5C33, text #FFFFFF
- Height 40px, border-radius 20px (pill), padding 10px 16px.
- Disabled state: opacity 0.4.

Also provides a module-level factory function ``create_button`` for
convenience.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk


# CSS class mapping for each variant.
_VARIANT_CLASSES: dict[str, str] = {
    "primary": "primary-btn",
    "secondary": "secondary-btn",
    "accent": "primary-btn",       # accent reuses primary styling
    "destructive": "destructive-btn",
}


class StyledButton(Gtk.Button):
    """Pill-shaped button matching the ByteCLI design system.

    Parameters
    ----------
    label:
        Button text.
    variant:
        Visual style -- ``"primary"``, ``"secondary"``, ``"destructive"``
        or ``"accent"``.
    """

    def __init__(self, label: str = "", variant: str = "primary") -> None:
        super().__init__(label=label)
        self._variant = variant
        self._disabled = False

        # Apply the variant CSS class.
        css_class = _VARIANT_CLASSES.get(variant, "primary-btn")
        self.add_css_class(css_class)
        self.add_css_class("mono")
        self.add_css_class("font-medium")

        # Destructive buttons need inline CSS because there is no global
        # .destructive-btn rule in the shared stylesheet -- add it here.
        if variant == "destructive":
            self._apply_destructive_css()

    def set_disabled(self, disabled: bool) -> None:
        """Toggle the disabled visual state and sensitivity."""
        self._disabled = disabled
        self.set_sensitive(not disabled)
        if disabled:
            self.add_css_class("disabled-btn")
        else:
            self.remove_css_class("disabled-btn")

    @property
    def disabled(self) -> bool:
        return self._disabled

    # ------------------------------------------------------------------
    # Internal styling
    # ------------------------------------------------------------------

    def _apply_destructive_css(self) -> None:
        provider = Gtk.CssProvider()
        css = (
            ".destructive-btn {"
            "  background-color: #FF5C33;"
            "  color: #FFFFFF;"
            "  border-radius: 999px;"
            "  min-height: 40px;"
            "  padding: 10px 16px;"
            "  font-weight: 600;"
            "  font-size: 14px;"
            "  border: none;"
            "  box-shadow: none;"
            "  outline: none;"
            "}"
            ".destructive-btn:hover {"
            "  background-color: shade(#FF5C33, 1.08);"
            "}"
            ".destructive-btn:active {"
            "  background-color: shade(#FF5C33, 0.9);"
            "}"
        )
        provider.load_from_data(css.encode())
        self.get_style_context().add_provider(
            provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def create_button(label: str, style: str = "primary") -> StyledButton:
    """Factory function that creates and returns a ``StyledButton``.

    Parameters
    ----------
    label:
        Button text.
    style:
        ``"primary"``, ``"secondary"``, or ``"destructive"``.
    """
    return StyledButton(label=label, variant=style)
