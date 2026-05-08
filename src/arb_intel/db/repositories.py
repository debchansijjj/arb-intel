"""Тонкие репозитории — encapsulate частые селекты/upserts.

Не плодим Active Record-стиль; репозитории получают AsyncSession снаружи.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arb_intel.db.models import (
    Chain,
    Opportunity,
    Pool,
    PoolState,
    SuspiciousPattern,
    Token,
    UniverseMembership,
)


# ---------------- chain ----------------
async def upsert_chain(sess: AsyncSession, *, name: str, family: str, chain_id: int | None) -> Chain:
    stmt = (
        pg_insert(Chain)
        .values(name=name, family=family, chain_id=chain_id, enabled=True, extra={})
        .on_conflict_do_update(index_elements=[Chain.name], set_={"family": family, "chain_id": chain_id})
        .returning(Chain)
    )
    return (await sess.execute(stmt)).scalar_one()


async def get_chain_by_name(sess: AsyncSession, name: str) -> Chain | None:
    return (await sess.execute(select(Chain).where(Chain.name == name))).scalar_one_or_none()


# ---------------- token ----------------
async def upsert_token(
    sess: AsyncSession,
    *,
    chain_id: int,
    address: str,
    symbol: str | None,
    name: str | None,
    decimals: int,
    is_stable: bool = False,
) -> Token:
    addr = address.lower()
    stmt = (
        pg_insert(Token)
        .values(
            chain_id=chain_id,
            address=addr,
            symbol=symbol,
            name=name,
            decimals=decimals,
            is_stable=is_stable,
            flags={},
        )
        .on_conflict_do_update(
            index_elements=[Token.chain_id, Token.address],
            set_={"symbol": symbol, "name": name, "decimals": decimals, "is_stable": is_stable},
        )
        .returning(Token)
    )
    return (await sess.execute(stmt)).scalar_one()


# ---------------- pool ----------------
async def upsert_pool(
    sess: AsyncSession,
    *,
    chain_id: int,
    address: str,
    dex: str,
    kind: str,
    token0_id: int,
    token1_id: int,
    fee_bps: int,
    extra: dict | None = None,
) -> Pool:
    stmt = (
        pg_insert(Pool)
        .values(
            chain_id=chain_id,
            address=address.lower(),
            dex=dex,
            kind=kind,
            token0_id=token0_id,
            token1_id=token1_id,
            fee_bps=fee_bps,
            extra=extra or {},
        )
        .on_conflict_do_update(
            index_elements=[Pool.chain_id, Pool.address],
            set_={"fee_bps": fee_bps, "extra": extra or {}},
        )
        .returning(Pool)
    )
    return (await sess.execute(stmt)).scalar_one()


async def list_pools_for_token(
    sess: AsyncSession, token_id: int, *, chain_ids: Sequence[int] | None = None
) -> Sequence[Pool]:
    stmt = select(Pool).where((Pool.token0_id == token_id) | (Pool.token1_id == token_id))
    if chain_ids:
        stmt = stmt.where(Pool.chain_id.in_(chain_ids))
    return (await sess.execute(stmt)).scalars().all()


async def upsert_pool_state(sess: AsyncSession, **values: object) -> None:
    if "pool_id" not in values:
        raise ValueError("pool_id required")
    stmt = pg_insert(PoolState).values(**values).on_conflict_do_update(
        index_elements=[PoolState.pool_id],
        set_={k: v for k, v in values.items() if k != "pool_id"},
    )
    await sess.execute(stmt)


# ---------------- opportunities ----------------
async def insert_opportunity(sess: AsyncSession, op: Opportunity) -> Opportunity:
    sess.add(op)
    await sess.flush()
    return op


# ---------------- universe ----------------
async def upsert_universe(
    sess: AsyncSession,
    token_id: int,
    *,
    tier: int,
    score: float,
    expires_at: datetime | None = None,
    reason: str | None = None,
) -> None:
    stmt = pg_insert(UniverseMembership).values(
        token_id=token_id,
        tier=tier,
        score=score,
        expires_at=expires_at,
        reason=reason,
    ).on_conflict_do_update(
        index_elements=[UniverseMembership.token_id],
        set_={"tier": tier, "score": score, "expires_at": expires_at, "reason": reason},
    )
    await sess.execute(stmt)


# ---------------- suspicious ----------------
async def insert_suspicious(sess: AsyncSession, items: Iterable[SuspiciousPattern]) -> None:
    for it in items:
        sess.add(it)
    await sess.flush()
