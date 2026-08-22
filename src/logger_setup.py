"""
logger_setup.py
----------------
Central logging configuration. Every module fetches its logger with
`get_logger(__name__)` so log lines are traceable to their source
module while still printing clean, user-facing status messages to
stdout (per the "Logging" requirements in the spec: "Loading image...",
"Running OCR...", etc.)
"""

import logging
import sys


_CONFIGURED = False


def setup_logging(level: str = "INFO"):
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("redditvideogen")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger("redditvideogen").getChild(name)


def status(msg: str):
    """A plain, user-facing progress line, e.g. 'Running OCR...'"""
    logging.getLogger("redditvideogen").info(msg)
