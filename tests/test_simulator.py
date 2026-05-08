"""Тест end-to-end симулятора (без БД/Redis).

Подменяем oracle.usd_price на детерминированную фейковую функцию через
monkeypatch.
"""

from __future__ import annotations

import pytest

from arb_intel.oracle.usd import TokenUsd
from arb_intel.simulation import simulator as sim
from arb_intel.tracking.pool_state import HotPoolState

WETH = "0x" + "00" * 19 + "11"
USDC = "0x" + "00" * 19 + "22"


def _v2(chain: str, dex: str, r0: int, r1: int) -> HotPoolState:
    return HotPoolState(
        chain=chain, pool=f"0x{dex[:8]:0>40}", dex=dex, kind="v2", fee_bps=30,
        token0=WETH, token1=USDC, decimals0=18, decimals1=6,
        reserve0=str(r0), reserve1=str(r1),
        implied_price=(r1 / 10**6) / (r0 / 10**18),
        ts=0.0, tvl_usd=10**6,
    )


@pytest.fixture(autouse=True)
def _fake_usd_price(monkeypatch):
    async def _fake(chain: str, addr: str):
        return TokenUsd(address=addr, chain=chain, usd=1.0, confidence=0.99)
    monkeypatch.setattr(sim, "usd_price", _fake)


async def test_simulate_profit_when_imbalanced_pools() -> None:
    # buy дешёвый: WETH 1ETH = 2900 USDC (token0=WETH, token1=USDC)
    buy = _v2("base", "uniswap_v3", r0=1000 * 10**18, r1=2_900_000 * 10**6)
    # sell дорогой: 1ETH = 3100 USDC
    sell = _v2("base", "aerodrome",  r0=1000 * 10**18, r1=3_100_000 * 10**6)

    res = await sim.simulate(buy, sell, 500.0)
    # Если базовый + квот стейбл, simple-математика должна показать профит
    assert res.feasible is True
    assert res.net_profit_usd > 0
    assert res.avg_slippage_bps >= 0


async def test_simulate_pair_mismatch_returns_infeasible() -> None:
    buy = _v2("base", "uni", 10**21, 10**12)
    other = HotPoolState(
        chain="base", pool="0xdiff", dex="aerodrome", kind="v2", fee_bps=30,
        token0=USDC, token1="0xfeed", decimals0=6, decimals1=18,
        reserve0=str(10**12), reserve1=str(10**21), implied_price=1.0, ts=0.0,
    )
    res = await sim.simulate(buy, other, 100.0)
    assert res.feasible is False
    assert res.rejection_reason == "pair_mismatch"


async def test_simulate_sizes_returns_per_size() -> None:
    buy = _v2("base", "u", 1000 * 10**18, 2_900_000 * 10**6)
    sell = _v2("base", "a", 1000 * 10**18, 3_100_000 * 10**6)
    out = await sim.simulate_sizes(buy, sell, [100, 500, 1000])
    assert len(out) == 3
    assert all(r.notional_usd in (100, 500, 1000) for r in out)
