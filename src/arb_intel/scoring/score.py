"""Multi-factor scoring engine.

Confidence ∈ [0, 1] — чем больше, тем выше вероятность, что
opportunity исполнится прибыльно. Веса откалиброваны эмпирически
и легко тюнятся.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arb_intel.heuristics.engine import HeuristicResult
from arb_intel.simulation.simulator import SimResult
from arb_intel.tracking.pool_state import HotPoolState


@dataclass(slots=True)
class ScoreResult:
    confidence: float
    breakdown: dict[str, float]


def _profit_score(net_usd: float) -> float:
    # 0 → 0; $1 → 0.05; $10 → 0.4; $100 → 0.85; $1000+ → 1.0
    if net_usd <= 0:
        return 0.0
    return min(1.0, math.log10(net_usd + 1) / 3.0)


def _slippage_score(slip_bps: float) -> float:
    # 0bps → 1; 50bps → 0.7; 200bps → 0.3; 500+bps → 0.05
    return max(0.05, 1.0 / (1.0 + slip_bps / 100.0))


def _spread_score(spread_bps: float) -> float:
    if spread_bps <= 0:
        return 0.0
    if spread_bps < 50:
        return 0.4
    if spread_bps < 200:
        return 0.7
    if spread_bps < 1000:
        return 0.9
    if spread_bps > 5000:
        # подозрительно широкий — penalize
        return 0.3
    return 0.95


def _kind_weight(kind: str) -> float:
    return {
        "lagging": 1.05,
        "fresh": 0.95,
        "cross-dex": 1.0,
        "intra-dex": 0.95,
        "cross-chain": 0.85,
    }.get(kind, 1.0)


def _bridge_penalty(net_usd: float, bridge_usd: float, eta_s: int | None) -> float:
    if not bridge_usd:
        return 1.0
    # чем выше fee/profit и чем длиннее ETA — тем сильнее penalty
    base = max(0.2, 1.0 - bridge_usd / max(net_usd, 1.0) * 0.5)
    if eta_s and eta_s > 300:
        base *= 0.85
    return base


def _depth_score(buy: HotPoolState, sell: HotPoolState, notional_usd: float) -> float:
    # очень примитивно: если у пулов есть extra.ds.liq и notional/liq < 1% — score высокий
    def _liq(p: HotPoolState) -> float:
        # heuristic: tvl_usd > 0; иначе очень осторожно
        if p.tvl_usd and p.tvl_usd > 0:
            return p.tvl_usd
        return 50_000.0  # дефолт; недостаток данных
    s = 1.0
    for p in (buy, sell):
        ratio = notional_usd / max(_liq(p), 1.0)
        if ratio > 0.05:
            s *= 0.4
        elif ratio > 0.01:
            s *= 0.75
    return s


def score_opportunity(
    *,
    kind: str,
    spread_bps: float,
    best: SimResult,
    heuristics: HeuristicResult,
    buy: HotPoolState,
    sell: HotPoolState,
) -> ScoreResult:
    profit = _profit_score(best.net_profit_usd)
    slippage = _slippage_score(best.avg_slippage_bps)
    spread = _spread_score(spread_bps)
    kindw = _kind_weight(kind)
    bridge = _bridge_penalty(best.net_profit_usd, best.bridge_usd, best.bridge_eta_s)
    depth = _depth_score(buy, sell, best.notional_usd)
    heur = max(0.0, min(1.0, heuristics.score))

    raw = (
        0.40 * profit
        + 0.20 * slippage
        + 0.15 * spread
        + 0.10 * depth
        + 0.10 * bridge
        + 0.05 * 1.0  # baseline
    ) * kindw * heur

    confidence = max(0.0, min(1.0, raw))
    return ScoreResult(
        confidence=confidence,
        breakdown={
            "profit": profit,
            "slippage": slippage,
            "spread": spread,
            "depth": depth,
            "bridge": bridge,
            "kind_w": kindw,
            "heur": heur,
        },
    )
