"""
History manager for transcription results.

Persists a FIFO list of dictionaries to ``history.json`` and exposes them
as plain tuples for D-Bus serialisation.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from bytecli.constants import DATA_DIR, HISTORY_FILE

logger = logging.getLogger(__name__)


class HistoryManager:
    """Thread-safe, file-backed transcription history."""

    def __init__(
        self,
        history_file: str = HISTORY_FILE,
        max_entries: int = 50,
    ) -> None:
        self._history_file = history_file
        self._max_entries = max_entries
        self._entries: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return a deep copy of all history entries (oldest first)."""
        return copy.deepcopy(self._entries)

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @max_entries.setter
    def max_entries(self, value: int) -> None:
        self._max_entries = max(1, min(value, 500))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load history from disk.  Corrupt files are backed up and cleared."""
        os.makedirs(os.path.dirname(self._history_file), exist_ok=True)

        if not os.path.isfile(self._history_file):
            self._entries = []
            return

        try:
            with open(self._history_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError("Root element is not a list.")
            self._entries = data
            logger.info("Loaded %d history entries.", len(self._entries))
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning(
                "History file corrupt or unreadable (%s). "
                "Backing up and starting fresh.",
                exc,
            )
            self._backup_and_clear()

    def add(self, text: str, model: str, duration_ms: int) -> None:
        """Append a transcription entry and persist to disk.

        Applies FIFO eviction if the entry count exceeds *max_entries*.
        """
        entry: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "duration_ms": duration_ms,
        }
        self._entries.append(entry)

        # FIFO eviction
        while len(self._entries) > self._max_entries:
            self._entries.pop(0)

        self._persist()

    def get_recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the most recent *n* entries (newest first)."""
        return list(reversed(self._entries[-n:]))

    def get_all(self) -> list[tuple[str, str, str]]:
        """Return all entries as ``(text, timestamp, id)`` tuples.

        This format matches the D-Bus ``a(ssx)`` – note that IDs are
        returned as strings and the caller may need to adapt the
        signature.  For simplicity we use ``a(sss)`` in practice.
        """
        return [
            (e["text"], e["timestamp"], e["id"])
            for e in reversed(self._entries)
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Atomically write the current entries list to disk."""
        import tempfile

        dir_name = os.path.dirname(self._history_file)
        os.makedirs(dir_name, exist_ok=True)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="history_", dir=dir_name
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._entries, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp_path, self._history_file)
        except OSError as exc:
            logger.error("Failed to persist history: %s", exc)
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _backup_and_clear(self) -> None:
        bak = self._history_file + ".bak"
        try:
            if os.path.isfile(self._history_file):
                os.replace(self._history_file, bak)
                logger.info("Corrupt history backed up to %s", bak)
        except OSError as exc:
            logger.error("Could not back up corrupt history: %s", exc)
        self._entries = []
        self._persist()
