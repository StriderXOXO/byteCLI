"""
Centralised logging configuration for all ByteCLI processes.

Creates a ``RotatingFileHandler`` writing to ``LOG_FILE`` (5 MB, 3 backups)
and a ``StreamHandler`` on *stderr* so that ``journalctl`` can also capture
output when running under *systemd*.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from bytecli.constants import LOG_FILE

_MAX_BYTES: int = 5 * 1024 * 1024   # 5 MB
_BACKUP_COUNT: int = 3
_FORMAT: str = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging(name: str) -> logging.Logger:
    """Configure and return a logger named *name*.

    * File handler: ``RotatingFileHandler`` writing to ``LOG_FILE``.
    * Stream handler: ``StreamHandler`` on *stderr*.
    * Log level defaults to ``DEBUG`` (file) and ``INFO`` (console).
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers when called more than once.
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    # --- File handler -------------------------------------------------------
    log_dir = os.path.dirname(LOG_FILE)
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # --- Console handler ----------------------------------------------------
    console_handler = logging.StreamHandler()  # stderr by default
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
