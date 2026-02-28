"""
PID file management for ByteCLI processes.

Provides helpers for single-instance enforcement via PID files located
under ``/run/user/$UID/``.
"""

from __future__ import annotations

import atexit
import errno
import logging
import os
import signal

logger = logging.getLogger(__name__)


class PidManager:
    """Create, check and clean up PID files."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def check_and_write(pid_file_path: str) -> None:
        """Ensure no other instance is running, then write the current PID.

        * If the PID file exists **and** the process is still alive, raise
          ``RuntimeError``.
        * If the PID file is stale (process dead), remove it first.
        * Write the current process PID and register an atexit cleanup.
        """
        if PidManager.is_running(pid_file_path):
            raise RuntimeError(
                f"Another instance is already running "
                f"(PID file: {pid_file_path})."
            )

        # Stale file may still be present – remove it.
        PidManager._remove(pid_file_path)

        # Write the current PID.
        os.makedirs(os.path.dirname(pid_file_path), exist_ok=True)
        try:
            with open(pid_file_path, "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
            logger.debug("PID file written: %s (pid=%d)", pid_file_path, os.getpid())
        except OSError as exc:
            logger.error("Failed to write PID file %s: %s", pid_file_path, exc)
            raise

        # Ensure cleanup on normal exit.
        atexit.register(PidManager.cleanup, pid_file_path)

    @staticmethod
    def cleanup(pid_file_path: str) -> None:
        """Remove the PID file if it belongs to the current process."""
        try:
            with open(pid_file_path, "r", encoding="utf-8") as fh:
                stored_pid = int(fh.read().strip())
        except (OSError, ValueError):
            # File already gone or unreadable – nothing to do.
            return

        if stored_pid == os.getpid():
            PidManager._remove(pid_file_path)
            logger.debug("PID file cleaned up: %s", pid_file_path)

    @staticmethod
    def is_running(pid_file_path: str) -> bool:
        """Return ``True`` if the PID file exists and a *different* process is alive.

        If the stored PID matches the current process (self-restart via
        ``os.execv``), this returns ``False`` so the restart can proceed.
        """
        if not os.path.isfile(pid_file_path):
            return False

        try:
            with open(pid_file_path, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            return False

        # Self-restart: os.execv keeps the same PID.
        if pid == os.getpid():
            return False

        return PidManager._process_alive(pid)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _process_alive(pid: int) -> bool:
        """Check whether *pid* is alive using ``os.kill(pid, 0)``."""
        try:
            os.kill(pid, 0)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                # No such process.
                return False
            if exc.errno == errno.EPERM:
                # Process exists but we lack permission to signal it –
                # treat as alive (belongs to another user, which is odd
                # for a per-user PID file but play it safe).
                return True
            return False
        return True

    @staticmethod
    def _remove(pid_file_path: str) -> None:
        """Silently remove *pid_file_path* if it exists."""
        try:
            os.unlink(pid_file_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not remove PID file %s: %s", pid_file_path, exc)
