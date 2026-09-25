"""Structured application logging (stdlib only, no extra dependency)."""

from __future__ import annotations

import logging
import sys

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once with a structured, greppable format."""
    global _configured
    if _configured:
        return
    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)
    # Quiet noisy third-party loggers slightly in development.
    logging.getLogger("uvicorn.access").setLevel(max(numeric, logging.WARNING))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
