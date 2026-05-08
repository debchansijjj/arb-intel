"""Structured JSON logging via structlog.

Используется по всему стэку. Корреляционные id прокидываются через
``contextvars`` (см. ``utils.context``).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from arb_intel.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # NOTE: используем PrintLoggerFactory (см. ниже), он не имеет .name —
    # поэтому stdlib.add_logger_name использовать нельзя, иначе каждый log.*
    # молча падает с AttributeError. add_log_level совместим с обоими.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        timestamper,
    ]

    if settings.log_json:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(stream=sys.stderr, level=level, format="%(message)s")
    # quiet noisy libs
    for noisy in ("websockets", "urllib3", "asyncio", "httpx", "web3", "solana"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
