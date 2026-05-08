from __future__ import annotations

from arb_intel.heuristics.engine import HeuristicResult
from arb_intel.scoring.score import score_opportunity
from arb_intel.simulation.simulator import SimResult
from arb_intel.tracking.pool_state import HotPoolState


def _hot(chain: str = "base", impl: float = 1.0, tvl: float = 250_000) -> HotPoolState:
    return HotPoolState(
        chain=chain, pool="0x" + "ab" * 20, dex="uniswap_v2", kind="v2", fee_bps=30,
        token0="0x" + "11" * 20, token1="0x" + "22" * 20, decimals0=18, decimals1=6,
        implied_price=impl, ts=0.0, tvl_usd=tvl,
    )


def _sim(net: float, slip_bps: float = 50.0, bridge: float = 0.0) -> SimResult:
    return SimResult(
        notional_usd=500.0, base_amount=10**18, quote_back=10**6, quote_in=10**6,
        gross_profit_usd=net + 2.0, fees_usd=0.0, gas_usd=2.0,
        bridge_usd=bridge, bridge_eta_s=120 if bridge else None,
        net_profit_usd=net, avg_slippage_bps=slip_bps,
        cross_chain=bool(bridge), feasible=net > 0,
    )


def test_high_profit_clean_heur_yields_high_confidence() -> None:
    res = score_opportunity(
        kind="cross-dex", spread_bps=120,
        best=_sim(net=80, slip_bps=20),
        heuristics=HeuristicResult(score=1.0),
        buy=_hot(), sell=_hot(impl=1.012),
    )
    assert 0.7 <= res.confidence <= 1.0


def test_low_profit_low_confidence() -> None:
    res = score_opportunity(
        kind="cross-dex", spread_bps=10,
        best=_sim(net=0.2, slip_bps=300),
        heuristics=HeuristicResult(score=1.0),
        buy=_hot(), sell=_hot(),
    )
    assert res.confidence < 0.55


def test_cross_chain_bridge_penalty_lower_than_same_chain() -> None:
    same = score_opportunity(
        kind="cross-dex", spread_bps=200,
        best=_sim(net=50, slip_bps=30, bridge=0),
        heuristics=HeuristicResult(score=1.0),
        buy=_hot(), sell=_hot(),
    )
    cross = score_opportunity(
        kind="cross-chain", spread_bps=200,
        best=_sim(net=50, slip_bps=30, bridge=8),
        heuristics=HeuristicResult(score=1.0),
        buy=_hot(chain="base"), sell=_hot(chain="arbitrum"),
    )
    assert cross.confidence < same.confidence


def test_fake_heuristic_zeroes_confidence() -> None:
    res = score_opportunity(
        kind="cross-dex", spread_bps=200,
        best=_sim(net=50, slip_bps=30),
        heuristics=HeuristicResult(score=0.0, is_fake=True),
        buy=_hot(), sell=_hot(),
    )
    assert res.confidence == 0.0


def test_breakdown_keys_present() -> None:
    res = score_opportunity(
        kind="lagging", spread_bps=80,
        best=_sim(net=10),
        heuristics=HeuristicResult(score=0.9),
        buy=_hot(), sell=_hot(),
    )
    assert {"profit", "slippage", "spread", "depth", "bridge", "kind_w", "heur"} <= set(res.breakdown)
