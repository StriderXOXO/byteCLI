"""
Text output via clipboard paste (``xclip`` + ``xdotool key``).

Copies the transcribed text to the X clipboard and simulates
``Ctrl+Shift+V`` into the focused window.  This shortcut works in both
terminal emulators and most GUI applications.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Tuple

logger = logging.getLogger(__name__)


def type_text(text: str) -> Tuple[bool, bool]:
    """Paste *text* into the focused window via clipboard.

    Returns
    -------
    (success, fallback_used) : tuple[bool, bool]
        * *success* – whether the text was delivered.
        * *fallback_used* – ``True`` when the paste simulation failed
          and the text was left on the clipboard instead.
    """
    if not text:
        return (True, False)

    # 1. Save the current clipboard content.
    saved_clipboard = _get_clipboard()

    # 2. Copy transcription to clipboard.
    if not _set_clipboard(text):
        return (False, False)

    # 3. Explicitly release all modifier keys that may still be "held"
    #    from the X server's perspective due to XGrabKey state.
    try:
        subprocess.run(
            ["xdotool", "keyup", "ctrl", "alt", "shift", "super"],
            timeout=3,
        )
    except Exception:
        pass

    time.sleep(0.05)

    # 4. Paste via Ctrl+Shift+V (works in both terminals and GUI apps).
    paste_key = "ctrl+shift+v"

    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", paste_key],
            check=True,
            timeout=5,
        )
        logger.debug(
            "Text pasted via %s (%d chars).", paste_key, len(text)
        )
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired) as exc:
        logger.warning("xdotool key %s failed: %s", paste_key, exc)
        # Text is still on the clipboard — user can paste manually.
        return (True, True)

    # 5. Restore the original clipboard after a short delay.
    if saved_clipboard is not None:
        time.sleep(0.2)
        _set_clipboard(saved_clipboard)

    return (True, False)


def copy_to_clipboard(text: str) -> bool:
    """Copy *text* to the X CLIPBOARD selection via ``xclip``."""
    return _set_clipboard(text)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _get_clipboard() -> str | None:
    """Return the current CLIPBOARD content, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _set_clipboard(text: str) -> bool:
    """Write *text* to the X CLIPBOARD selection."""
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired) as exc:
        logger.error("xclip write failed: %s", exc)
        return False
