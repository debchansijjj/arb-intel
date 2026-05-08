"""USD-оценка для toкенов через состояние стейбл-пар.

Стратегия:
- Знаем известные стейблы (USDC/USDT/DAI/...) — у них USD≈1.
- Для остальных токенов смотрим самые ликвидные пулы token/stable
  в Redis hot-state. Берём implied_price на топ-1/2 пулах и медиану.
- WETH/WSOL/WBTC и пр. квот-токены — fallback к DexScreener-ценам,
  которые мы кладём в `Pool.extra.ds.px_usd` при бутстрапе. Этого
  достаточно для оценки notional (нам не нужна биржевая точность).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select

from arb_intel.cache.redis_client import get_redis, ns
from arb_intel.db.models import Chain, Pool, Token
from arb_intel.db.session import session_scope

STABLE_SYMS = {"USDC", "USDT", "DAI", "FDUSD", "BUSD", "TUSD", "USDC.E", "USDBC"}


@dataclass(slots=True)
class TokenUsd:
    address: str
    chain: str
    usd: float
    confidence: float


async def usd_price(chain: str, token_address: str) -> TokenUsd | None:
    address = token_address.lower()
    # известный стейбл — fast path по символу из БД
    async with session_scope() as sess:
        chain_row = (await sess.execute(select(Chain).where(Chain.name == chain))).scalar_one_or_none()
        if chain_row is None:
            return None
        token_row = (
            await sess.execute(
                select(Token).where(Token.chain_id == chain_row.id, Token.address == address)
            )
        ).scalar_one_or_none()
        if token_row is None:
            return None
        if token_row.is_stable or (token_row.symbol or "").upper() in STABLE_SYMS:
            return TokenUsd(address=address, chain=chain, usd=1.0, confidence=0.99)

        # ищем пулы token/stable
        pools = (
            await sess.execute(
                select(Pool, Token.id, Token.address, Token.symbol, Token.is_stable)
                .join(Token, Token.id == Pool.token1_id)
                .where(Pool.chain_id == chain_row.id, Pool.token0_id == token_row.id)
            )
        ).all()
    r = get_redis()
    samples: list[float] = []
    for pool_row, _qid, _qaddr, qsym, q_is_stable in pools:
        is_stable = bool(q_is_stable) or (qsym or "").upper() in STABLE_SYMS
        if not is_stable:
            continue
        raw = await r.get(ns("pool", chain, pool_row.address.lower()))
        if not raw:
            continue
        import orjson
        d = orjson.loads(raw)
        ip = float(d.get("implied_price") or 0)
        if ip <= 0:
            continue
        samples.append(ip)
    if samples:
        usd = statistics.median(samples)
        return TokenUsd(address=address, chain=chain, usd=usd, confidence=min(0.95, 0.5 + 0.1 * len(samples)))

    # fallback: DexScreener-кеш в pool.extra.ds.px_usd
    async with session_scope() as sess:
        pools = (
            await sess.execute(
                select(Pool).where(Pool.chain_id == chain_row.id).where(
                    (Pool.token0_id == token_row.id) | (Pool.token1_id == token_row.id)
                )
            )
        ).scalars().all()
    fallbacks: list[float] = []
    for p in pools:
        ds = (p.extra or {}).get("ds") or {}
        px = ds.get("px_usd")
        if isinstance(px, (int, float)) and px > 0:
            fallbacks.append(float(px))
    if fallbacks:
        return TokenUsd(address=address, chain=chain, usd=statistics.median(fallbacks), confidence=0.4)
    return None
