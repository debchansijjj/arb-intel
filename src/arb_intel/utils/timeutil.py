"""Time helpers."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def now_ts() -> float:
    return time.time()


def now_ms() -> int:
    return int(time.time() * 1000)


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)
