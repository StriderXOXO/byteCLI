"""
ByteCLI shared constants.

Centralises all paths, D-Bus identifiers, timeouts, recording parameters,
design tokens, Whisper model metadata and default configuration values used
across the three ByteCLI processes.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------
CONFIG_DIR: str = os.path.join(os.path.expanduser("~"), ".config", "bytecli")
DATA_DIR: str = os.path.join(os.path.expanduser("~"), ".local", "share", "bytecli")

CONFIG_FILE: str = os.path.join(CONFIG_DIR, "config.json")
HISTORY_FILE: str = os.path.join(DATA_DIR, "history.json")
LOG_FILE: str = os.path.join(DATA_DIR, "logs", "bytecli.log")
MODEL_DIR: str = os.path.join(DATA_DIR, "models")

_UID: str = str(os.getuid())
PID_FILE: str = os.path.join("/run", "user", _UID, "bytecli.pid")
INDICATOR_PID_FILE: str = os.path.join("/run", "user", _UID, "bytecli-indicator.pid")

# ---------------------------------------------------------------------------
# D-Bus identifiers
# ---------------------------------------------------------------------------
DBUS_BUS_NAME: str = "com.bytecli.Service"
DBUS_OBJECT_PATH: str = "/com/bytecli/Service"
DBUS_INTERFACE: str = "com.bytecli.ServiceInterface"

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
START_TIMEOUT: int = 30
STOP_TIMEOUT: int = 10
MODEL_SWITCH_TIMEOUT: int = 60
RESTART_TIMEOUT: int = 40

# ---------------------------------------------------------------------------
# Recording parameters
# ---------------------------------------------------------------------------
MIN_RECORDING_DURATION: float = 0.3   # seconds – ignore shorter presses
MAX_RECORDING_DURATION: float = 300.0  # seconds – auto-stop ceiling
AUDIO_SAMPLE_RATE: int = 16000         # Hz (Whisper requirement)
AUDIO_CHANNELS: int = 1                # mono
AUDIO_BUFFER_FRAMES: int = 1024        # frames per callback

# ---------------------------------------------------------------------------
# Design token colours (dark theme)
# ---------------------------------------------------------------------------
COLORS: dict[str, str] = {
    "background": "#111111",
    "foreground": "#FFFFFF",
    "card": "#1A1A1A",
    "muted": "#2E2E2E",
    "muted_foreground": "#B8B9B6",
    "primary": "#FF8400",
    "primary_foreground": "#111111",
    "border": "#2E2E2E",
    "secondary": "#2E2E2E",
    "secondary_foreground": "#FFFFFF",
    "success_foreground": "#B6FFCE",
    "error_foreground": "#FF5C33",
    "warning_foreground": "#FF8400",
    "info_foreground": "#B2B2FF",
    "input": "#2E2E2E",
    "destructive": "#FF5C33",
}

# ---------------------------------------------------------------------------
# Whisper model catalogue
# ---------------------------------------------------------------------------
WHISPER_MODELS: dict[str, dict[str, str]] = {
    "tiny": {
        "display_name": "Fast (tiny)",
        "size": "~75 MB",
    },
    "small": {
        "display_name": "Balanced (small)",
        "size": "~465 MB",
    },
    "medium": {
        "display_name": "Accurate (medium)",
        "size": "~1.5 GB",
    },
}

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict = {
    "model": "small",
    "device": "gpu",
    "audio_input": "auto",
    "hotkey": {
        "keys": ["Ctrl", "Alt", "V"],
    },
    "language": "en",
    "auto_start": False,
    "history_max_entries": 50,
}
