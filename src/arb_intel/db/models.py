"""Доменная модель.

Таблицы:
    chains                 — справочник сетей
    tokens                 — токены
    pools                  — DEX-пулы
    pool_states            — последний state каждого пула (hot row)
    swaps                  — наблюдаемые свопы (партиционировано по дням)
    liquidity_snapshots    — реверсивные снимки резервов / sqrtPrice
    opportunities          — найденные арбитражные окна
    suspicious_patterns    — anti-fake findings
    alerts                 — отправленные telegram-алерты (для дедупа/аналитики)
    universe_membership    — какие токены в каких уровнях универса (1/2/3)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arb_intel.db.base import Base, bigint_pk, created_at_column, updated_at_column


class Chain(Base):
    __tablename__ = "chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    family: Mapped[str] = mapped_column(String(16), nullable=False)  # evm | solana | other
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (
        UniqueConstraint("chain_id", "address", name="uq_tokens_chain_address"),
        Index("ix_tokens_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer, ForeignKey("chains.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(String(96), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    decimals: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    is_stable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flags: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Pool(Base):
    __tablename__ = "pools"
    __table_args__ = (
        UniqueConstraint("chain_id", "address", name="uq_pools_chain_address"),
        Index("ix_pools_dex", "dex"),
        Index("ix_pools_token0_token1", "token0_id", "token1_id"),
        Index("ix_pools_first_seen_at", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer, ForeignKey("chains.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str] = mapped_column(String(96), nullable=False)
    dex: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # v2|v3|v4|whirlpool|raydium|dlmm|pumpswap
    token0_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tokens.id", ondelete="RESTRICT"))
    token1_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tokens.id", ondelete="RESTRICT"))
    fee_bps: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class PoolState(Base):
    """Hot row — обновляется каждый раз, когда наблюдается изменение state."""

    __tablename__ = "pool_states"

    pool_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True
    )
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    slot: Mapped[int | None] = mapped_column(BigInteger)  # solana
    reserve0: Mapped[str | None] = mapped_column(Numeric(80, 0))
    reserve1: Mapped[str | None] = mapped_column(Numeric(80, 0))
    sqrt_price_x96: Mapped[str | None] = mapped_column(Numeric(80, 0))
    tick: Mapped[int | None] = mapped_column(Integer)
    liquidity: Mapped[str | None] = mapped_column(Numeric(80, 0))
    fee_growth_global0: Mapped[str | None] = mapped_column(Numeric(80, 0))
    fee_growth_global1: Mapped[str | None] = mapped_column(Numeric(80, 0))
    last_swap_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Swap(Base):
    __tablename__ = "swaps"
    __table_args__ = (
        Index("ix_swaps_pool_observed_at", "pool_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pools.id", ondelete="CASCADE"), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, ForeignKey("chains.id"), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(96), index=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    slot: Mapped[int | None] = mapped_column(BigInteger)
    log_index: Mapped[int | None] = mapped_column(Integer)
    sender: Mapped[str | None] = mapped_column(String(96), index=True)
    side: Mapped[str | None] = mapped_column(String(8))  # buy|sell|swap
    amount0_in: Mapped[str | None] = mapped_column(Numeric(80, 0))
    amount1_in: Mapped[str | None] = mapped_column(Numeric(80, 0))
    amount0_out: Mapped[str | None] = mapped_column(Numeric(80, 0))
    amount1_out: Mapped[str | None] = mapped_column(Numeric(80, 0))
    price: Mapped[float | None] = mapped_column(Float)
    usd_value: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class LiquiditySnapshot(Base):
    __tablename__ = "liquidity_snapshots"
    __table_args__ = (
        Index("ix_liqsnap_pool_taken_at", "pool_id", "taken_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pools.id", ondelete="CASCADE"), nullable=False)
    reserve0: Mapped[str | None] = mapped_column(Numeric(80, 0))
    reserve1: Mapped[str | None] = mapped_column(Numeric(80, 0))
    sqrt_price_x96: Mapped[str | None] = mapped_column(Numeric(80, 0))
    tick: Mapped[int | None] = mapped_column(Integer)
    liquidity: Mapped[str | None] = mapped_column(Numeric(80, 0))
    implied_price: Mapped[float | None] = mapped_column(Float)
    tvl_usd: Mapped[float | None] = mapped_column(Float)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        Index("ix_opps_kind_score_created", "kind", "score", "created_at"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
    )

    id: Mapped[int] = bigint_pk()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_token_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tokens.id"))
    quote_token_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tokens.id"))
    buy_pool_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pools.id"))
    sell_pool_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pools.id"))
    buy_chain_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chains.id"))
    sell_chain_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chains.id"))
    spread_bps: Mapped[float | None] = mapped_column(Float)
    notional_usd: Mapped[float | None] = mapped_column(Float)
    gross_profit_usd: Mapped[float | None] = mapped_column(Float)
    net_profit_usd: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SuspiciousPattern(Base):
    __tablename__ = "suspicious_patterns"

    id: Mapped[int] = bigint_pk()
    pool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pools.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    detected_at: Mapped[datetime] = created_at_column()


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("fingerprint", "chat_id", name="uq_alerts_fingerprint_chat"),
        Index("ix_alerts_sent_at", "sent_at"),
    )

    id: Mapped[int] = bigint_pk()
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opportunity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("opportunities.id"))
    sent_at: Mapped[datetime] = created_at_column()
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class UniverseMembership(Base):
    __tablename__ = "universe_membership"
    __table_args__ = (
        UniqueConstraint("token_id", name="uq_universe_token"),
        Index("ix_universe_tier", "tier"),
    )

    id: Mapped[int] = bigint_pk()
    token_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tokens.id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 broad / 2 active / 3 hot
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    promoted_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
