"""
Configuration manager for the ByteCLI service.

Loads, validates, and persists ``config.json`` using atomic writes.  Corrupt
files are backed up and replaced with defaults so the service always has a
usable configuration.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from typing import Any

from bytecli.constants import CONFIG_DIR, CONFIG_FILE, DEFAULT_CONFIG, WHISPER_MODELS

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages the ByteCLI user configuration on disk."""

    def __init__(self, config_file: str = CONFIG_FILE) -> None:
        self._config_file = config_file
        self._config: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> dict[str, Any]:
        """Return a *copy* of the current configuration dict."""
        return copy.deepcopy(self._config)

    @property
    def config_file(self) -> str:
        return self._config_file

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load config from disk, falling back to defaults on any error."""
        os.makedirs(os.path.dirname(self._config_file), exist_ok=True)

        if not os.path.isfile(self._config_file):
            logger.info("No config file found – creating with defaults.")
            self._config = self.get_default_config()
            self.save(self._config)
            return self.config

        try:
            with open(self._config_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Config file corrupt or unreadable (%s). "
                "Backing up and resetting to defaults.",
                exc,
            )
            self._backup_corrupt_file()
            self._config = self.get_default_config()
            self.save(self._config)
            return self.config

        # Merge loaded data onto defaults so new keys are always present.
        merged = self.get_default_config()
        merged.update(data)
        # Ensure nested dicts (hotkey) are merged properly.
        if "hotkey" in data and isinstance(data["hotkey"], dict):
            default_hotkey = self.get_default_config()["hotkey"]
            default_hotkey.update(data["hotkey"])
            merged["hotkey"] = default_hotkey

        errors = self.validate(merged)
        if errors:
            logger.warning(
                "Config validation errors: %s. Using defaults for bad fields.",
                errors,
            )
            # Fall back to defaults for every invalid field.
            defaults = self.get_default_config()
            for field in errors:
                key_parts = field.split(".")
                if len(key_parts) == 2:
                    merged.setdefault(key_parts[0], {})[key_parts[1]] = (
                        defaults[key_parts[0]][key_parts[1]]
                    )
                else:
                    merged[field] = defaults[field]

        self._config = merged
        return self.config

    def save(self, config_dict: dict[str, Any]) -> None:
        """Atomically write *config_dict* to disk (write-then-rename)."""
        os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
        dir_name = os.path.dirname(self._config_file)

        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="config_", dir=dir_name
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(config_dict, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp_path, self._config_file)
            self._config = copy.deepcopy(config_dict)
            logger.debug("Config saved to %s", self._config_file)
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)
            # Clean up the temp file if the rename failed.
            if "tmp_path" in locals() and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def validate(self, config_dict: dict[str, Any]) -> list[str]:
        """Return a list of field names that fail validation (empty == OK)."""
        errors: list[str] = []

        # model
        if config_dict.get("model") not in WHISPER_MODELS:
            errors.append("model")

        # device
        if config_dict.get("device") not in ("gpu", "cpu"):
            errors.append("device")

        # audio_input – must be a non-empty string
        ai = config_dict.get("audio_input")
        if not isinstance(ai, str) or not ai:
            errors.append("audio_input")

        # hotkey
        hk = config_dict.get("hotkey")
        if not isinstance(hk, dict):
            errors.append("hotkey")
        else:
            if hk.get("mode") not in ("double", "triple"):
                errors.append("hotkey.mode")
            keys = hk.get("keys")
            if (
                not isinstance(keys, list)
                or not (2 <= len(keys) <= 3)
                or not all(isinstance(k, str) and k for k in keys)
            ):
                errors.append("hotkey.keys")

        # language
        if config_dict.get("language") not in ("en", "zh"):
            errors.append("language")

        # auto_start
        if not isinstance(config_dict.get("auto_start"), bool):
            errors.append("auto_start")

        # history_max_entries
        hme = config_dict.get("history_max_entries")
        if not isinstance(hme, int) or not (1 <= hme <= 500):
            errors.append("history_max_entries")

        return errors

    @staticmethod
    def get_default_config() -> dict[str, Any]:
        """Return a deep copy of the built-in default configuration."""
        return copy.deepcopy(DEFAULT_CONFIG)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _backup_corrupt_file(self) -> None:
        bak = self._config_file + ".bak"
        try:
            if os.path.isfile(self._config_file):
                os.replace(self._config_file, bak)
                logger.info("Corrupt config backed up to %s", bak)
        except OSError as exc:
            logger.error("Could not back up corrupt config: %s", exc)
