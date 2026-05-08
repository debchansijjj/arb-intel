"""Token Universe Engine.

Три уровня:
  Tier 1 (broad)   — токены, замеченные хотя бы в одном пуле >= min_liquidity_usd
                     или в bootstrap-источниках. Не торгуем — наблюдаем.
  Tier 2 (active)  — есть свежие свопы и/или volatility, ликвидность ≥ X,
                     минимум одна пара на стейбле. Сюда подключаем расширенное
                     отслеживание state-изменений.
  Tier 3 (hot)     — свежий пул, или liquidity migration / fragmented liquidity
                     across DEXes / chains. Самый узкий и самый важный круг для
                     поиска лагов и арбитража.

Промоушен/демоушен — через Redis hot-state + периодическая
консолидация в Postgres (`UniverseMembership`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from arb_intel.cache import redis_client as cache
from arb_intel.config import get_settings
from arb_intel.db.repositories import upsert_universe
from arb_intel.db.session import session_scope
from arb_intel.logging import get_logger
from arb_intel.utils.timeutil import now_utc

log = get_logger(__name__)


@dataclass(slots=True)
class UniverseSignal:
    chain: str
    token_address: str
    score_delta: float
    reason: str
    promote_hint: int | None = None  # 1 / 2 / 3 если хотим явно поднять


class UniverseEngine:
    """Принимает сигналы из discovery/tracking/heuristics, обновляет tier-membership."""

    def __init__(self) -> None:
        s = get_settings()
        self._min_liq_t1 = s.discovery.min_liquidity_usd
        self._min_liq_t2 = s.discovery.min_liquidity_usd * 5
        self._min_vol_t2 = s.discovery.min_volume_24h_usd
        self._max_per_chain = s.discovery.max_tokens_per_chain
        self._lock = asyncio.Lock()

    async def ingest(self, signals: Iterable[UniverseSignal]) -> None:
        async with session_scope() as sess:
            for sig in signals:
                # сюда мы не пишем сразу tier — accumulate в Redis,
                # tier выставляется промоутером ниже.
                key = cache.ns("universe", sig.chain, sig.token_address.lower())
                pipe = cache.get_redis().pipeline(transaction=False)
                pipe.hincrbyfloat(key, "score", sig.score_delta)
                pipe.hset(key, mapping={"reason": sig.reason})
                pipe.expire(key, int(timedelta(days=2).total_seconds()))
                await pipe.execute()
                # tier hint promotion (cheap path)
                if sig.promote_hint:
                    token_id = await self._resolve_token_id(sess, sig.chain, sig.token_address)
                    if token_id is not None:
                        await upsert_universe(
                            sess,
                            token_id,
                            tier=sig.promote_hint,
                            score=float(sig.score_delta),
                            expires_at=now_utc() + timedelta(hours=12),
                            reason=sig.reason,
                        )

    async def _resolve_token_id(self, sess, chain: str, address: str) -> int | None:
        # local import to avoid cycle on type-check
        from sqlalchemy import select

        from arb_intel.db.models import Chain, Token

        chain_row = (await sess.execute(select(Chain).where(Chain.name == chain))).scalar_one_or_none()
        if chain_row is None:
            return None
        token_row = (
            await sess.execute(
                select(Token).where(Token.chain_id == chain_row.id, Token.address == address.lower())
            )
        ).scalar_one_or_none()
        return token_row.id if token_row else None

    async def consolidate(self) -> None:
        """Периодически переводим redis-scores → tier в Postgres.

        Tier rules:
          score >= 100 → tier 3
          score >=  20 → tier 2
          else         → tier 1
        """
        r = cache.get_redis()
        async with session_scope() as sess:
            count = 0
            async for key in r.scan_iter(match=cache.ns("universe", "*"), count=500):
                key_s = key.decode() if isinstance(key, bytes) else key
                _, _, chain, addr = key_s.split(":")
                fields = await r.hgetall(key)
                score = float(fields.get(b"score", b"0") or 0)
                reason = (fields.get(b"reason") or b"").decode()
                tier = 3 if score >= 100 else 2 if score >= 20 else 1
                token_id = await self._resolve_token_id(sess, chain, addr)
                if token_id is None:
                    continue
                await upsert_universe(
                    sess,
                    token_id,
                    tier=tier,
                    score=score,
                    expires_at=now_utc() + timedelta(hours=24),
                    reason=reason,
                )
                count += 1
            log.info("universe.consolidate", updated=count)
