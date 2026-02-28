"""
Global hotkey manager using python-xlib ``XGrabKey``.

Registers a key combination with all common lock-mask variants (NumLock,
CapsLock, both) and runs an X11 event loop in a dedicated daemon thread.
Callbacks are dispatched to the GLib main loop via ``GLib.idle_add`` to
ensure thread safety with the rest of the service.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from typing import Callable, List, Optional

from gi.repository import GLib

from Xlib import X, XK, display as xdisplay, error as xerror

logger = logging.getLogger(__name__)

# Lock masks that we need to account for so that hotkeys still fire
# when NumLock / CapsLock / ScrollLock are active.
_NUM_LOCK_MASK = 1 << 4   # Mod2Mask (typical)
_CAPS_LOCK_MASK = X.LockMask
_SCROLL_LOCK_MASK = 1 << 5  # Mod3Mask (typical)

_LOCK_MASKS: list[int] = [
    0,
    _NUM_LOCK_MASK,
    _CAPS_LOCK_MASK,
    _NUM_LOCK_MASK | _CAPS_LOCK_MASK,
    _SCROLL_LOCK_MASK,
    _NUM_LOCK_MASK | _SCROLL_LOCK_MASK,
    _CAPS_LOCK_MASK | _SCROLL_LOCK_MASK,
    _NUM_LOCK_MASK | _CAPS_LOCK_MASK | _SCROLL_LOCK_MASK,
]

# Mapping from human-readable modifier names to X modifier masks.
_MOD_MAP: dict[str, int] = {
    "ctrl": X.ControlMask,
    "control": X.ControlMask,
    "alt": X.Mod1Mask,
    "shift": X.ShiftMask,
    "super": X.Mod4Mask,
    "meta": X.Mod4Mask,
}


class HotkeyManager:
    """Register / unregister a global hotkey via X11 grabs."""

    def __init__(self) -> None:
        self._display: Optional[xdisplay.Display] = None
        self._root = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Current hotkey state.
        self._keys: list[str] = []
        self._modifier_mask: int = 0
        self._keycode: int = 0

        # Callback.
        self._on_press: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    # Callback setters
    # ------------------------------------------------------------------

    def on_press(self, callback: Callable[[], None]) -> None:
        """Set the callback invoked on hotkey press (via ``GLib.idle_add``)."""
        self._on_press = callback

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, keys_list: List[str]) -> None:
        """Parse *keys_list*, grab the key combination and start the event loop.

        Parameters
        ----------
        keys_list:
            Human-readable key names, e.g. ``["Ctrl", "Alt", "V"]``.
        """
        self.unregister()  # clean up any previous grab

        self._display = xdisplay.Display()
        self._root = self._display.screen().root

        self._keys = keys_list
        self._modifier_mask, self._keycode = self._parse_keys(keys_list)

        if self._keycode == 0:
            raise ValueError(f"Could not resolve keysym for keys: {keys_list}")

        # Grab with every lock-mask combination.
        for extra_mask in _LOCK_MASKS:
            self._root.grab_key(
                self._keycode,
                self._modifier_mask | extra_mask,
                True,
                X.GrabModeAsync,
                X.GrabModeAsync,
            )

        self._display.flush()
        logger.info("Hotkey registered: %s (keycode=%d, mask=0x%X)",
                     "+".join(keys_list), self._keycode, self._modifier_mask)

        # Start the event loop thread.
        self._running = True
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()

    def unregister(self) -> None:
        """Ungrab the current hotkey and stop the event thread."""
        self._running = False

        if self._root is not None and self._keycode:
            try:
                for extra_mask in _LOCK_MASKS:
                    self._root.ungrab_key(
                        self._keycode,
                        self._modifier_mask | extra_mask,
                    )
                self._display.flush()
                logger.debug("Hotkey unregistered.")
            except Exception as exc:
                logger.warning("Error ungrabbing hotkey: %s", exc)

        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
            self._display = None
            self._root = None

        self._keycode = 0
        self._modifier_mask = 0

        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ------------------------------------------------------------------
    # Temporary ungrab / regrab (used during clipboard paste)
    # ------------------------------------------------------------------

    def ungrab(self) -> None:
        """Temporarily release the hotkey grab so that simulated key
        events (e.g. ``xdotool key ctrl+v``) are not intercepted."""
        if self._root is None or self._keycode == 0:
            return
        try:
            for extra_mask in _LOCK_MASKS:
                self._root.ungrab_key(
                    self._keycode,
                    self._modifier_mask | extra_mask,
                )
            self._display.sync()
            logger.debug("Hotkey temporarily ungrabbed.")
        except Exception as exc:
            logger.warning("ungrab failed: %s", exc)

    def regrab(self) -> None:
        """Re-establish the hotkey grab after a temporary release."""
        if self._root is None or self._keycode == 0:
            return
        try:
            for extra_mask in _LOCK_MASKS:
                self._root.grab_key(
                    self._keycode,
                    self._modifier_mask | extra_mask,
                    True,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                )
            self._display.flush()
            logger.debug("Hotkey re-grabbed.")
        except Exception as exc:
            logger.warning("regrab failed: %s", exc)

    # ------------------------------------------------------------------
    # Keyboard grab helpers (for custom-capture mode)
    # ------------------------------------------------------------------

    def grab_keyboard(self) -> None:
        """Grab the entire keyboard (for hotkey capture dialogs)."""
        if self._root is None:
            return
        self._root.grab_keyboard(
            True, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime
        )
        self._display.flush()
        logger.debug("Full keyboard grabbed.")

    def ungrab_keyboard(self) -> None:
        """Release a full keyboard grab."""
        if self._display is None:
            return
        self._display.ungrab_keyboard(X.CurrentTime)
        self._display.flush()
        logger.debug("Keyboard ungrabbed.")

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    @staticmethod
    def check_conflict(keys_list: List[str]) -> Optional[str]:
        """Check GNOME keybindings for conflicts via ``gsettings``.

        Returns the name of the conflicting binding, or ``None``.
        """
        target = "+".join(k.lower() for k in keys_list)

        schemas = [
            "org.gnome.desktop.wm.keybindings",
            "org.gnome.settings-daemon.plugins.media-keys",
            "org.gnome.shell.keybindings",
        ]

        for schema in schemas:
            try:
                result = subprocess.run(
                    ["gsettings", "list-recursively", schema],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    continue

                for line in result.stdout.splitlines():
                    # Lines look like:
                    # org.gnome.desktop.wm.keybindings switch-windows ['<Alt>Tab']
                    parts = line.split(None, 2)
                    if len(parts) < 3:
                        continue
                    key_name = parts[1]
                    value = parts[2].lower()
                    # Normalise angle-bracket notation to our format.
                    normalised = (
                        value
                        .replace("<primary>", "ctrl+")
                        .replace("<ctrl>", "ctrl+")
                        .replace("<alt>", "alt+")
                        .replace("<shift>", "shift+")
                        .replace("<super>", "super+")
                        .replace("'", "")
                        .replace("[", "")
                        .replace("]", "")
                        .strip()
                    )
                    if target in normalised:
                        source = f"{schema} {key_name}"
                        logger.warning("Hotkey conflict: %s -> %s", target, source)
                        return source
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

        return None

    # ------------------------------------------------------------------
    # Internal: X event loop
    # ------------------------------------------------------------------

    def _event_loop(self) -> None:
        """Block on X events in a daemon thread, dispatching to GLib."""
        logger.debug("X11 hotkey event loop started.")

        # We need our own error handler because the default one calls exit().
        def _error_handler(err, *args):
            logger.debug("Xlib error (ignored): %s", err)

        self._display.set_error_handler(_error_handler)

        while self._running:
            try:
                count = self._display.pending_events()
                if count == 0:
                    # Use select-style wait with timeout to allow clean exit.
                    import select
                    rlist, _, _ = select.select(
                        [self._display.fileno()], [], [], 0.5
                    )
                    if not rlist:
                        continue
                    count = self._display.pending_events()

                for _ in range(count):
                    event = self._display.next_event()

                    if event.type == X.KeyPress:
                        if self._on_press is not None:
                            GLib.idle_add(self._on_press)

            except Exception as exc:
                if self._running:
                    logger.error("Error in hotkey event loop: %s", exc)
                break

        logger.debug("X11 hotkey event loop exited.")

    # ------------------------------------------------------------------
    # Internal: key parsing
    # ------------------------------------------------------------------

    def _parse_keys(self, keys_list: List[str]) -> tuple[int, int]:
        """Convert human-readable key names to (modifier_mask, keycode).

        The last non-modifier key is treated as the primary key.
        """
        modifier_mask = 0
        primary_key: Optional[str] = None

        for key in keys_list:
            lower = key.lower()
            if lower in _MOD_MAP:
                modifier_mask |= _MOD_MAP[lower]
            else:
                primary_key = key

        if primary_key is None:
            return (0, 0)

        keysym = XK.string_to_keysym(primary_key)
        if keysym == 0:
            # Try common aliases.
            keysym = XK.string_to_keysym(primary_key.lower())
        if keysym == 0:
            logger.error("Cannot resolve keysym for '%s'.", primary_key)
            return (modifier_mask, 0)

        keycode = self._display.keysym_to_keycode(keysym)
        return (modifier_mask, keycode)
