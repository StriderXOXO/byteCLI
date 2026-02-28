"""
HotkeyConfigSection -- hotkey mode, key preset and custom-capture configuration.

Provides:
* Mode dropdown: "Double Key" / "Triple Key"
* Key preset dropdown filtered by the selected mode
  - Double: Ctrl+V, Alt+V, Ctrl+R, Alt+R, Ctrl+D
  - Triple: Ctrl+Alt+V, Ctrl+Shift+V, Ctrl+Alt+R, Ctrl+Shift+R, Ctrl+Alt+D
* "Custom" button that enters capture mode:
  - Input box with orange 2px dashed border, "Press your hotkey..." placeholder
  - Cancel link to exit capture without applying
* Validation feedback:
  - Green "Available" text on success
  - Red "Conflict with {source}" text on conflict, auto-revert, and
    modal conflict dialog
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from bytecli.i18n import i18n
from bytecli.shared.dbus_client import DBusClient
from bytecli.settings.widgets.section_card import SectionCard
from bytecli.settings.widgets.styled_button import StyledButton

logger = logging.getLogger(__name__)

# Preset hotkey combos grouped by mode, matching the design spec.
_PRESETS: dict[str, list[list[str]]] = {
    "double": [
        ["Ctrl", "V"],
        ["Alt", "V"],
        ["Ctrl", "R"],
        ["Alt", "R"],
        ["Ctrl", "D"],
    ],
    "triple": [
        ["Ctrl", "Alt", "V"],
        ["Ctrl", "Shift", "V"],
        ["Ctrl", "Alt", "R"],
        ["Ctrl", "Shift", "R"],
        ["Ctrl", "Alt", "D"],
    ],
}

_MODE_LABELS: dict[str, str] = {
    "double": "Double Key",
    "triple": "Triple Key",
}


def _keys_display(keys: list[str]) -> str:
    """Format a key list as a human-readable combo string."""
    return " + ".join(keys)


# Normalisation table for raw X key names -> display names.
_KEY_NAME_MAP: dict[str, str] = {
    "control_l": "Ctrl",
    "control_r": "Ctrl",
    "alt_l": "Alt",
    "alt_r": "Alt",
    "shift_l": "Shift",
    "shift_r": "Shift",
    "super_l": "Super",
    "super_r": "Super",
    "meta_l": "Super",
    "meta_r": "Super",
    "space": "Space",
    "return": "Return",
    "tab": "Tab",
    "backspace": "BackSpace",
}

_MODIFIERS = frozenset({"Ctrl", "Alt", "Shift", "Super"})


def _normalise_key_name(raw: str) -> Optional[str]:
    """Normalise a Gdk key name to a display-friendly string.

    Returns ``None`` for Escape (used to cancel capture).
    """
    lower = raw.lower()

    if lower == "escape":
        return None

    if lower in _KEY_NAME_MAP:
        return _KEY_NAME_MAP[lower]

    # Single alphabetic character -> uppercase.
    if len(raw) == 1 and raw.isalpha():
        return raw.upper()

    # Function keys, digits, etc.
    return raw.capitalize()


class HotkeyConfigSection(Gtk.Box):
    """Hotkey configuration with mode / key dropdowns and custom capture."""

    def __init__(
        self,
        dbus_client: DBusClient,
        config: dict[str, Any],
        on_changed: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._dbus_client = dbus_client
        self._config = config
        self._on_changed = on_changed
        self._capturing = False
        self._captured_keys: list[str] = []
        self._suppress_signal = False

        hotkey = config.get("hotkey", {})
        self._current_mode: str = hotkey.get("mode", "double")
        self._current_keys: list[str] = list(
            hotkey.get("keys", ["Ctrl", "Alt", "V"])
        )

        self._card = SectionCard(
            title=i18n.t("settings.hotkey.title", fallback="Hotkey")
        )

        # --- Row 1: Mode dropdown ---
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode_row.set_margin_bottom(8)

        self._mode_label = Gtk.Label(
            label=i18n.t("settings.hotkey.mode", fallback="Mode:")
        )
        self._mode_label.add_css_class("text-base")
        self._mode_label.set_halign(Gtk.Align.START)
        mode_row.append(self._mode_label)

        self._mode_list = Gtk.StringList()
        for mode_key in ("double", "triple"):
            display = i18n.t(
                f"settings.hotkey.mode_{mode_key}",
                fallback=_MODE_LABELS[mode_key],
            )
            self._mode_list.append(display)

        self._mode_dropdown = Gtk.DropDown(model=self._mode_list)
        self._mode_dropdown.add_css_class("dropdown-btn")
        self._mode_dropdown.set_hexpand(True)
        self._mode_dropdown.connect("notify::selected", self._on_mode_changed)
        mode_row.append(self._mode_dropdown)

        self._card.card_content.append(mode_row)

        # --- Row 2: Key preset dropdown + Custom button ---
        key_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        key_row.set_margin_bottom(8)

        self._key_label = Gtk.Label(
            label=i18n.t("settings.hotkey.key", fallback="Key:")
        )
        self._key_label.add_css_class("text-base")
        self._key_label.set_halign(Gtk.Align.START)
        key_row.append(self._key_label)

        self._key_list = Gtk.StringList()
        self._key_dropdown = Gtk.DropDown(model=self._key_list)
        self._key_dropdown.add_css_class("dropdown-btn")
        self._key_dropdown.set_hexpand(True)
        self._key_dropdown.connect("notify::selected", self._on_key_changed)
        key_row.append(self._key_dropdown)

        # Custom capture entry (replaces dropdown during capture).
        self._capture_entry = Gtk.Entry()
        self._capture_entry.set_placeholder_text(
            i18n.t(
                "settings.hotkey.press_keys",
                fallback="Press your hotkey...",
            )
        )
        self._capture_entry.add_css_class("hotkey-capture")
        self._capture_entry.set_hexpand(True)
        self._capture_entry.set_visible(False)
        self._capture_entry.set_editable(False)

        # Key event controller for capture.
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_press)
        key_ctrl.connect("key-released", self._on_key_release)
        self._capture_entry.add_controller(key_ctrl)
        key_row.append(self._capture_entry)

        # Custom button.
        self._custom_btn = StyledButton(
            label=i18n.t("settings.hotkey.custom", fallback="Custom"),
            variant="secondary",
        )
        self._custom_btn.add_css_class("btn-sm")
        self._custom_btn.connect("clicked", self._on_custom_clicked)
        key_row.append(self._custom_btn)

        self._card.card_content.append(key_row)

        # --- Cancel link + hint (visible during capture) ---
        self._capture_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self._capture_row.set_margin_top(4)
        self._capture_row.set_visible(False)

        cancel_btn = Gtk.Button(
            label=i18n.t("settings.hotkey.cancel_capture", fallback="Cancel")
        )
        cancel_btn.add_css_class("link-label")
        cancel_btn.add_css_class("icon-btn")
        cancel_btn.connect("clicked", self._on_cancel_capture)
        self._capture_row.append(cancel_btn)

        hint = Gtk.Label(
            label=i18n.t(
                "settings.hotkey.capture_hint",
                fallback="Press and release your desired key combination",
            )
        )
        hint.add_css_class("text-muted")
        hint.add_css_class("text-sm")
        hint.set_halign(Gtk.Align.START)
        self._capture_row.append(hint)

        self._card.card_content.append(self._capture_row)

        # --- Feedback row ---
        self._feedback_label = Gtk.Label()
        self._feedback_label.add_css_class("text-sm")
        self._feedback_label.set_halign(Gtk.Align.START)
        self._feedback_label.set_margin_top(6)
        self._card.card_content.append(self._feedback_label)

        self.append(self._card)

        # --- Initial setup ---
        self._suppress_signal = True
        self._mode_dropdown.set_selected(
            0 if self._current_mode == "double" else 1
        )
        self._suppress_signal = False

        self._populate_key_presets(self._current_mode)
        self._select_current_key(self._current_keys)
        self._update_feedback(available=True)

    # ------------------------------------------------------------------
    # Mode / key changes
    # ------------------------------------------------------------------

    def _on_mode_changed(self, dropdown, param) -> None:
        if self._suppress_signal:
            return

        mode = "double" if dropdown.get_selected() == 0 else "triple"
        self._current_mode = mode
        self._populate_key_presets(mode)

        # Auto-select the first preset for the new mode.
        presets = _PRESETS.get(mode, [])
        if presets:
            self._current_keys = list(presets[0])

        self._apply_hotkey_to_config()
        self._validate_hotkey()

    def _on_key_changed(self, dropdown, param) -> None:
        if self._suppress_signal:
            return

        idx = dropdown.get_selected()
        presets = _PRESETS.get(self._current_mode, [])
        if 0 <= idx < len(presets):
            self._current_keys = list(presets[idx])
        # If idx falls beyond presets (custom entry), keys are already set.

        self._apply_hotkey_to_config()
        self._validate_hotkey()

    def _populate_key_presets(self, mode: str) -> None:
        """Rebuild the key dropdown entries for the given mode."""
        self._suppress_signal = True

        while self._key_list.get_n_items() > 0:
            self._key_list.remove(0)

        presets = _PRESETS.get(mode, [])
        for combo in presets:
            self._key_list.append(_keys_display(combo))

        # If the current keys aren't one of the presets, append them
        # as a custom entry so they remain visible.
        if self._current_keys not in presets:
            self._key_list.append(_keys_display(self._current_keys))

        if self._key_list.get_n_items() > 0:
            self._key_dropdown.set_selected(0)

        self._suppress_signal = False

    def _select_current_key(self, keys: list[str]) -> None:
        """Set the dropdown selection to match *keys*."""
        presets = _PRESETS.get(self._current_mode, [])
        for i, combo in enumerate(presets):
            if combo == keys:
                self._suppress_signal = True
                self._key_dropdown.set_selected(i)
                self._suppress_signal = False
                return

        # If keys match a custom entry appended at the end:
        n = self._key_list.get_n_items()
        if n > len(presets):
            self._suppress_signal = True
            self._key_dropdown.set_selected(n - 1)
            self._suppress_signal = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_hotkey(self) -> None:
        """Ask the service (or fall back locally) whether the hotkey conflicts."""
        result = self._dbus_client.validate_hotkey(
            self._current_mode, self._current_keys
        )

        if result is None:
            # Service unreachable -- try local check.
            self._check_conflict_locally()
            return

        is_valid = result.get("valid", True)
        conflict = result.get("conflict", result.get("conflict_source", ""))

        if is_valid:
            self._update_feedback(available=True)
        else:
            self._handle_conflict(conflict)

    def _check_conflict_locally(self) -> None:
        """Fallback conflict check using HotkeyManager.check_conflict."""
        try:
            from bytecli.service.hotkey_manager import HotkeyManager

            conflict = HotkeyManager.check_conflict(self._current_keys)
        except Exception:
            conflict = None

        if conflict is None:
            self._update_feedback(available=True)
        else:
            self._handle_conflict(conflict)

    def _handle_conflict(self, source: str) -> None:
        """Show conflict feedback, revert keys and pop the conflict dialog."""
        self._update_feedback(available=False, conflict=source)

        # Save the attempted keys for the dialog message.
        attempted_display = _keys_display(self._current_keys)

        # Revert to the previous saved keys.
        prev_hotkey = self._config.get("hotkey", {})
        self._current_mode = prev_hotkey.get("mode", "double")
        self._current_keys = list(
            prev_hotkey.get("keys", ["Ctrl", "Alt", "V"])
        )

        self._suppress_signal = True
        self._mode_dropdown.set_selected(
            0 if self._current_mode == "double" else 1
        )
        self._suppress_signal = False
        self._populate_key_presets(self._current_mode)
        self._select_current_key(self._current_keys)

        # Show the modal conflict dialog.
        try:
            from bytecli.settings.dialogs.hotkey_conflict import (
                HotkeyConflictDialog,
            )

            parent = self.get_root()
            dialog = HotkeyConflictDialog(
                parent=parent,
                keys=attempted_display,
                source=source,
                prev_keys=_keys_display(self._current_keys),
            )
            dialog.present()
        except Exception as exc:
            logger.error("Failed to show conflict dialog: %s", exc)

    def _update_feedback(
        self, available: bool, conflict: str = ""
    ) -> None:
        if available:
            self._feedback_label.set_text(
                i18n.t("settings.hotkey.available", fallback="Available")
            )
            self._feedback_label.remove_css_class("text-error")
            self._feedback_label.add_css_class("text-success")
        else:
            msg = i18n.t(
                "settings.hotkey.conflict",
                source=conflict,
                fallback=f"Conflict with {conflict}",
            )
            self._feedback_label.set_text(msg)
            self._feedback_label.remove_css_class("text-success")
            self._feedback_label.add_css_class("text-error")

    # ------------------------------------------------------------------
    # Custom capture
    # ------------------------------------------------------------------

    def _on_custom_clicked(self, btn) -> None:
        """Enter hotkey capture mode."""
        self._capturing = True
        self._captured_keys.clear()
        self._key_dropdown.set_visible(False)
        self._capture_entry.set_visible(True)
        self._capture_entry.set_text("")
        self._capture_entry.grab_focus()
        self._capture_row.set_visible(True)
        self._custom_btn.set_visible(False)

    def _on_cancel_capture(self, btn) -> None:
        """Exit capture mode without applying."""
        self._exit_capture()

    def _exit_capture(self) -> None:
        self._capturing = False
        self._captured_keys.clear()
        self._capture_entry.set_visible(False)
        self._key_dropdown.set_visible(True)
        self._capture_row.set_visible(False)
        self._custom_btn.set_visible(True)

    def _on_key_press(self, controller, keyval, keycode, state) -> bool:
        """Accumulate key names while the user holds modifier+primary."""
        if not self._capturing:
            return False

        raw_name = Gdk.keyval_name(keyval)
        if raw_name is None:
            return True

        normalised = _normalise_key_name(raw_name)

        # Escape cancels capture.
        if normalised is None:
            self._exit_capture()
            return True

        if normalised not in self._captured_keys:
            self._captured_keys.append(normalised)
            self._capture_entry.set_text(_keys_display(self._captured_keys))

        return True

    def _on_key_release(self, controller, keyval, keycode, state) -> None:
        """On release, accept the combination if it has >= 2 keys."""
        if not self._capturing:
            return
        if len(self._captured_keys) < 2:
            return

        # Must have at least one modifier and one primary key.
        modifiers = [k for k in self._captured_keys if k in _MODIFIERS]
        primaries = [k for k in self._captured_keys if k not in _MODIFIERS]
        if not modifiers or not primaries:
            return

        # Accept the captured keys.
        keys = list(self._captured_keys)
        self._exit_capture()

        # Determine the implied mode from key count.
        if len(keys) == 2:
            self._current_mode = "double"
        elif len(keys) >= 3:
            self._current_mode = "triple"

        self._current_keys = keys
        self._suppress_signal = True
        self._mode_dropdown.set_selected(
            0 if self._current_mode == "double" else 1
        )
        self._suppress_signal = False
        self._populate_key_presets(self._current_mode)
        self._select_current_key(self._current_keys)

        self._apply_hotkey_to_config()
        self._validate_hotkey()

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _apply_hotkey_to_config(self) -> None:
        self._config["hotkey"] = {
            "mode": self._current_mode,
            "keys": list(self._current_keys),
        }
        self._on_changed()

    # ------------------------------------------------------------------
    # Config interface (called by SettingsWindow)
    # ------------------------------------------------------------------

    def collect_config(self, config: dict) -> None:
        config["hotkey"] = {
            "mode": self._current_mode,
            "keys": list(self._current_keys),
        }

    def apply_config(self, config: dict) -> None:
        hotkey = config.get("hotkey", {})
        self._current_mode = hotkey.get("mode", "double")
        self._current_keys = list(
            hotkey.get("keys", ["Ctrl", "Alt", "V"])
        )

        self._suppress_signal = True
        self._mode_dropdown.set_selected(
            0 if self._current_mode == "double" else 1
        )
        self._suppress_signal = False

        self._populate_key_presets(self._current_mode)
        self._select_current_key(self._current_keys)
        self._update_feedback(available=True)

    def refresh_labels(self) -> None:
        self._card.set_title(
            i18n.t("settings.hotkey.title", fallback="Hotkey")
        )
        self._mode_label.set_text(
            i18n.t("settings.hotkey.mode", fallback="Mode:")
        )
        self._key_label.set_text(
            i18n.t("settings.hotkey.key", fallback="Key:")
        )
        self._custom_btn.set_label(
            i18n.t("settings.hotkey.custom", fallback="Custom")
        )
        self._capture_entry.set_placeholder_text(
            i18n.t(
                "settings.hotkey.press_keys",
                fallback="Press your hotkey...",
            )
        )

        # Rebuild mode dropdown labels.
        self._suppress_signal = True
        current_idx = self._mode_dropdown.get_selected()
        while self._mode_list.get_n_items() > 0:
            self._mode_list.remove(0)
        for mode_key in ("double", "triple"):
            display = i18n.t(
                f"settings.hotkey.mode_{mode_key}",
                fallback=_MODE_LABELS[mode_key],
            )
            self._mode_list.append(display)
        self._mode_dropdown.set_selected(current_idx)
        self._suppress_signal = False
