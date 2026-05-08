"""Корреляционные контексты для трейсинга event-pipeline."""

from __future__ import annotations

import contextvars
import secrets
from collections.abc import Iterator
from contextlib import contextmanager

import structlog

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def new_request_id() -> str:
    return secrets.token_hex(8)


def get_request_id() -> str | None:
    return _request_id_var.get()


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    rid = request_id or new_request_id()
    token = _request_id_var.set(rid)
    structlog.contextvars.bind_contextvars(rid=rid)
    try:
        yield rid
    finally:
        _request_id_var.reset(token)
        structlog.contextvars.unbind_contextvars("rid")
