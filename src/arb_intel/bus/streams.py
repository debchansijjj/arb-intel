"""Event bus поверх Redis Streams.

Зачем не pub/sub: нужны гарантии доставки и группы потребителей.
Зачем не Kafka/NATS на старте: лишний инфра-узел; адаптер позволяет
переключиться на NATS JetStream без переписывания продюсеров.

Формат сообщений: orjson-сериализованные dict, payload-агностично.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import orjson
import redis.asyncio as aioredis

from arb_intel.cache.redis_client import get_redis, ns
from arb_intel.config import get_settings
from arb_intel.logging import get_logger

log = get_logger(__name__)


# ---------------- streams ----------------
class Streams:
    POOL_STATE = "events.pool_state"     # каждое наблюдение state-изменения
    POOL_NEW = "events.pool_new"         # обнаружен новый пул
    SWAP = "events.swap"                 # наблюдаемый своп
    LIQUIDITY_DELTA = "events.liq_delta" # add/remove liquidity
    OPP_CANDIDATE = "events.opp_candidate"  # сырой кандидат от scanner
    OPP_RANKED = "events.opp_ranked"     # отсимулированный + scored
    ALERT = "events.alert"               # готовый телеграм-payload


def _stream_key(name: str) -> str:
    return ns("stream", name)


@dataclass(slots=True)
class Message:
    id: str
    payload: dict[str, Any]


# ---------------- producer ----------------
async def publish(stream: str, payload: dict[str, Any]) -> str:
    r = get_redis()
    s = get_settings()
    body = {"d": orjson.dumps(payload)}
    return (
        await r.xadd(_stream_key(stream), body, maxlen=s.bus.max_len, approximate=True)  # type: ignore[arg-type]
    ).decode()


async def publish_many(stream: str, payloads: list[dict[str, Any]]) -> None:
    if not payloads:
        return
    r = get_redis()
    s = get_settings()
    pipe = r.pipeline(transaction=False)
    for p in payloads:
        pipe.xadd(_stream_key(stream), {"d": orjson.dumps(p)}, maxlen=s.bus.max_len, approximate=True)
    await pipe.execute()


# ---------------- consumer ----------------
async def ensure_group(stream: str, group: str) -> None:
    r = get_redis()
    key = _stream_key(stream)
    try:
        await r.xgroup_create(key, group, id="$", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def consume(
    stream: str,
    group: str,
    consumer: str,
    *,
    block_ms: int = 2000,
    count: int = 64,
) -> AsyncIterator[Message]:
    r = get_redis()
    key = _stream_key(stream)
    await ensure_group(stream, group)
    last_id = ">"
    while True:
        try:
            res = await r.xreadgroup(group, consumer, {key: last_id}, count=count, block=block_ms)
        except aioredis.ConnectionError:
            log.warning("bus.consume.connection_error", stream=stream)
            await asyncio.sleep(1.0)
            continue
        if not res:
            continue
        for _stream, entries in res:
            for entry_id, fields in entries:
                try:
                    payload = orjson.loads(fields[b"d"])
                except Exception:
                    log.exception("bus.parse_error", stream=stream, entry=entry_id)
                    await r.xack(key, group, entry_id)
                    continue
                msg = Message(id=entry_id.decode(), payload=payload)
                yield msg
                await r.xack(key, group, entry_id)
