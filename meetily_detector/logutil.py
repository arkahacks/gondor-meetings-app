"""Rotating local file logging (FR-11). No telemetry — logs never leave the box."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler

# Matches a Google Meet code (xxx-xxxx-xxx) anywhere in a message so it can be
# redacted when the user opts in (Sec. 7 privacy invariant).
_MEET_CODE = re.compile(r"\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b")


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _MEET_CODE.sub("<meet-code>", record.msg)
        return True


def setup_logging(
    path: str,
    level: str = "INFO",
    max_bytes: int = 1_048_576,
    backup_count: int = 3,
    redact_meeting_code: bool = False,
) -> logging.Logger:
    """Configure the package logger to write to a rotating file (and stderr)."""
    logger = logging.getLogger("meetily_detector")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    expanded = os.path.expanduser(path)
    os.makedirs(os.path.dirname(expanded), exist_ok=True)
    file_handler = RotatingFileHandler(
        expanded, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    if redact_meeting_code:
        logger.addFilter(_RedactFilter())

    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("meetily_detector")
