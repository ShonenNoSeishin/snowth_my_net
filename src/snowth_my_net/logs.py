"""Logging: UTC timestamps on stderr, optional rotating log file, secret redaction.

Every loaded secret is registered with :data:`REDACTOR`; the formatter masks any occurrence of
a registered value in the final log line (message, arguments and tracebacks included), so a
secret that leaks into an exception text or a ``community@vlan`` string never reaches a log.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import time

LOGGER_NAME = "snowth_my_net"
MASK = "***"


class Redactor:
    """Registry of secret values that must never appear in any output."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def add(self, value: str) -> None:
        if value:
            with self._lock:
                self._values.add(value)

    def redact(self, text: str) -> str:
        if not self._values:
            return text
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for value in values:
            if value in text:
                text = text.replace(value, MASK)
        return text

    def clear(self) -> None:
        """Forget every registered value (tests only)."""
        with self._lock:
            self._values.clear()


REDACTOR = Redactor()


class RedactingFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )

    def format(self, record: logging.LogRecord) -> str:
        return REDACTOR.redact(super().format(record))


def setup_logging(level: str = "info", log_file: str | None = None, quiet: bool = False,
                  stderr_output: bool = True) -> None:
    """Configure the ``snowth_my_net`` logger tree. Safe to call more than once.

    ``stderr_output=False`` is used by the TUI, which shows logs in its own panel.
    """
    root = logging.getLogger(LOGGER_NAME)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level.upper())
    root.propagate = False

    if stderr_output:
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(RedactingFormatter())
        if quiet:
            stderr.setLevel(logging.WARNING)
        root.addHandler(stderr)

    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(RedactingFormatter())
        root.addHandler(file_handler)

    if not root.handlers:
        # Without any handler, Python would print warnings to stderr through its "last resort"
        # handler, over the terminal interface. The TUI shows logs in its own panels instead.
        root.addHandler(logging.NullHandler())

    # pysnmp's own debug output can contain community strings: keep it quiet whatever happens.
    logging.getLogger("pysnmp").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
