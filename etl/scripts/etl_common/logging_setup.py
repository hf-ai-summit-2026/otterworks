"""Stdlib logging configured to match the legacy ETL log line format.

The scripts used to emit ``print("[%s] ..." % timestamp)`` lines to stdout,
which cron appends to ``/var/log/etl/*.log``. This formatter keeps that
shape: ``[YYYY-MM-DD HH:MM:SS] message`` for INFO and below, and
``[YYYY-MM-DD HH:MM:SS] LEVEL: message`` for WARNING and above.
"""

import logging
import sys

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class LegacyFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(fmt="[%(asctime)s] %(message)s", datefmt=DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        if record.levelno >= logging.WARNING:
            prefix = "[%s] " % self.formatTime(record, self.datefmt)
            line = "%s%s: %s" % (prefix, record.levelname, line[len(prefix):])
        return line


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configure root logging to stdout and return a logger for ``name``."""
    # Fatal errors were logged as "FATAL: ..." by the legacy scripts.
    logging.addLevelName(logging.CRITICAL, "FATAL")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(LegacyFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    # Keep third-party chatter (botocore, urllib3) out of the ETL logs.
    for noisy in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger(name)
