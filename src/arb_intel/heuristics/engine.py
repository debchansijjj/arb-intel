"""Anti-fake heuristics engine.

Цель — отбросить или дауевейтить кандидатов, у которых "арбитраж"
существует только из-за манипуляций / honeypot / wash trading.

Сигналы:
  H1. Ликвидность too low: TVL обоих пулов < threshold → даунвейт.
  H2. Honeypot guess: соотношение buys/sells по DexScreener данным <0.05
      или >20 (подделка) — даунвейт. Жёстко детектится только в pull-
      логах transferable=false (выносим в отдельный воркер).
  H3. Wallet diversity: количество уникальных swappers за окно. Сейчас —
      из БД ``swaps``: если на пуле <5 уникальных адресов за час — фейк.
  H4. LP concentration: если в Postgres у нас есть top-LP holders >80%
      → wash candidate.
  H5. Reserve consistency: если implied_price скачет вне распределения
      других пулов > 5σ — отдельный сигнал.
  H6. Persistence: пул существует <60 секунд — допускаем, но это сразу
      повышает риск: если симуляция уже видит профит, отдельная метка
      "fresh" уже даёт ему больше веса в score, но heuristics уменьшает
      confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from arb_intel.db.models import Pool, Swap
from arb_intel.db.session import session_scope
from arb_intel.tracking.pool_state import HotPoolState
from arb_intel.utils.timeutil import now_utc


@dataclass(slots=True)
class HeuristicResult:
    score: float = 1.0  # 1.0 = чисто; ниже — подозрительно
    reasons: list[str] = field(default_factory=list)
    is_fake: bool = False


class HeuristicEngine:
    def __init__(self) -> None:
        self._min_tvl_usd = 5_000.0

    async def _pool_tvl_estimate(self, pool: HotPoolState) -> float | None:
        # из extra.ds.liq если есть
        async with session_scope() as sess:
            row = (
                await sess.execute(
                    select(Pool).where(
                        Pool.address == pool.pool,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            ds = (row.extra or {}).get("ds") or {}
            v = ds.get("liq")
            if isinstance(v, (int, float)):
                return float(v)
            gt = (row.extra or {}).get("gt") or {}
            v = gt.get("liq")
            if isinstance(v, (int, float)):
                return float(v)
        return None

    async def _wallet_diversity(self, pool: HotPoolState) -> int:
        async with session_scope() as sess:
            since = now_utc() - timedelta(hours=1)
            row = (
                await sess.execute(
                    select(Pool).where(Pool.address == pool.pool)
                )
            ).scalar_one_or_none()
            if row is None:
                return 0
            n = (
                await sess.execute(
                    select(func.count(func.distinct(Swap.sender)))
                    .where(Swap.pool_id == row.id, Swap.observed_at >= since)
                )
            ).scalar()
            return int(n or 0)

    async def evaluate(self, buy: HotPoolState, sell: HotPoolState) -> HeuristicResult:
        out = HeuristicResult()

        for pool in (buy, sell):
            tvl = await self._pool_tvl_estimate(pool)
            if tvl is None:
                # неизвестный пул из bootstrap'а — не наказываем сильно
                out.score *= 0.95
                out.reasons.append(f"{pool.pool[:8]}:tvl_unknown")
            elif tvl < self._min_tvl_usd:
                out.score *= 0.5
                out.reasons.append(f"{pool.pool[:8]}:tvl_low_${tvl:.0f}")

            # wallet diversity (cheap lookup)
            divers = await self._wallet_diversity(pool)
            if divers != 0 and divers < 5:
                out.score *= 0.6
                out.reasons.append(f"{pool.pool[:8]}:diversity_{divers}")

        # Reserve consistency: если spread огромен (>10000bps), почти гарантированно манипуляция.
        if buy.implied_price > 0 and sell.implied_price > 0:
            ratio = max(buy.implied_price, sell.implied_price) / min(buy.implied_price, sell.implied_price)
            if ratio > 5.0:
                out.score *= 0.2
                out.reasons.append(f"ratio_outlier_{ratio:.1f}")
                out.is_fake = ratio > 20.0

        return out
