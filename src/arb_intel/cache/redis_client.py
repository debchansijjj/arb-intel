"""Redis client + namespaced helpers (dedup, cooldown, hot pool state)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import orjson
import redis.asyncio as aioredis

from arb_intel.config import get_settings

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        s = get_settings()
        _client = aioredis.from_url(
            s.redis.url,
            encoding="utf-8",
            decode_responses=False,
            socket_timeout=s.redis.socket_timeout_s,
            health_check_interval=20,
        )
    return _client


def ns(*parts: str) -> str:
    s = get_settings()
    return ":".join((s.redis.namespace, *parts))


# ---------------- generic kv with json ----------------
async def get_json(key: str) -> Any | None:
    r = get_redis()
    raw = await r.get(key)
    if raw is None:
        return None
    return orjson.loads(raw)


async def set_json(key: str, value: Any, ttl_s: int | None = None) -> None:
    r = get_redis()
    await r.set(key, orjson.dumps(value), ex=ttl_s)


# ---------------- dedup / cooldown ----------------
async def dedup(fingerprint: str, ttl_s: int) -> bool:
    """Return True if this fingerprint is fresh (not seen recently)."""
    r = get_redis()
    key = ns("dedup", fingerprint)
    # SET NX EX
    res = await r.set(key, b"1", nx=True, ex=ttl_s)
    return bool(res)


async def cooldown_ok(scope: str, key: str, cooldown_s: int) -> bool:
    return await dedup(f"cd:{scope}:{key}", cooldown_s)


def fingerprint(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


# ---------------- hot pool state ----------------
def pool_state_key(chain: str, pool_addr: str) -> str:
    return ns("pool", chain.lower(), pool_addr.lower())


async def write_pool_state(chain: str, pool_addr: str, state: dict[str, Any], ttl_s: int = 3600) -> None:
    await set_json(pool_state_key(chain, pool_addr), state, ttl_s=ttl_s)


async def read_pool_state(chain: str, pool_addr: str) -> dict[str, Any] | None:
    return await get_json(pool_state_key(chain, pool_addr))


async def scan_pool_states(chain: str | None = None) -> AsyncIterator[dict[str, Any]]:
    r = get_redis()
    pattern = ns("pool", chain or "*", "*")
    async for key in r.scan_iter(match=pattern, count=500):
        raw = await r.get(key)
        if raw:
            yield orjson.loads(raw)


# ---------------- watch keys ----------------
async def remember_seen(scope: str, key: str, ttl_s: int) -> None:
    r = get_redis()
    await r.set(ns("seen", scope, key), str(int(time.time())).encode(), ex=ttl_s)


async def have_seen(scope: str, key: str) -> bool:
    r = get_redis()
    return await r.exists(ns("seen", scope, key)) == 1


@asynccontextmanager
async def lock(name: str, ttl_s: int = 30) -> AsyncIterator[bool]:
    r = get_redis()
    key = ns("lock", name)
    acquired = await r.set(key, b"1", nx=True, ex=ttl_s)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            await r.delete(key)


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
