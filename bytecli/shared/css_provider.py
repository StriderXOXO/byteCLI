"""
CSS provider loader for ByteCLI.

Reads ``bytecli/data/bytecli.css`` and installs the stylesheet on the default
GDK display so that all GTK 4 widgets in the process pick up the
ByteCLI design tokens automatically.

Usage (typically called once during application startup):

    from bytecli.shared.css_provider import load_css
    load_css()
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Resolve the path to bytecli/data/bytecli.css relative to the package root.
# Works for both editable (pip install -e .) and non-editable installs.
import bytecli as _bytecli_pkg

_CSS_PATH = os.path.join(os.path.dirname(_bytecli_pkg.__file__), "data", "bytecli.css")


def load_css() -> None:
    """Load the ByteCLI CSS stylesheet and apply it to the default display.

    This must be called **after** ``Gtk.init()`` (or after the ``Gtk.Application``
    has been constructed) so that a default display is available.

    Raises no exceptions -- errors are logged and the application continues
    with the GTK default styling.
    """
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk
    except (ImportError, ValueError) as exc:
        logger.error("GTK 4 Python bindings are not available: %s", exc)
        return

    if not os.path.isfile(_CSS_PATH):
        logger.error("CSS file not found: %s", _CSS_PATH)
        return

    provider = Gtk.CssProvider()

    try:
        provider.load_from_path(_CSS_PATH)
    except Exception as exc:
        logger.error("Failed to parse CSS file %s: %s", _CSS_PATH, exc)
        return

    display = Gdk.Display.get_default()
    if display is None:
        logger.error("No default GDK display -- cannot apply CSS.")
        return

    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    logger.debug("ByteCLI CSS loaded from %s", _CSS_PATH)
