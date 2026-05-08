"""Тесты математики AMM-кривых.

Цель: убедиться, что v2/v3 формулы возвращают разумные числа.
"""

from __future__ import annotations

import math

from arb_intel.simulation.curves import (
    Q96,
    V3PoolSnapshot,
    v2_amount_out,
    v2_price_impact_bps,
    v3_amount_out_in_range,
    whirlpool_amount_out_in_range,
)


def test_v2_xyk_invariant_basic() -> None:
    # Большие резервы, чтобы избежать integer-truncation: 1e9 на 1e9, fee 30bps.
    out = v2_amount_out(10**6, 10**9, 10**9, 30)
    # ~ 996_006 (xy=k минус fee)
    assert 900_000 < out < 1_000_000
    # И с маленьким размером тоже порядок верен
    out2 = v2_amount_out(1_000, 10**9, 10**9, 30)
    assert 990 < out2 < 1_000


def test_v2_zero_input_or_zero_reserves() -> None:
    assert v2_amount_out(0, 1000, 1000, 30) == 0
    assert v2_amount_out(100, 0, 1000, 30) == 0
    assert v2_amount_out(100, 1000, 0, 30) == 0


def test_v2_price_impact_monotonic() -> None:
    """С большим amount_in price impact должен расти."""
    impact_small = v2_price_impact_bps(10, 10_000, 10_000, 30)
    impact_big = v2_price_impact_bps(2_000, 10_000, 10_000, 30)
    assert impact_big > impact_small
    assert impact_big > 100  # >= 1%


def test_v2_fee_reduces_output() -> None:
    out_no_fee = v2_amount_out(1000, 100_000, 100_000, 0)
    out_30 = v2_amount_out(1000, 100_000, 100_000, 30)
    out_100 = v2_amount_out(1000, 100_000, 100_000, 100)
    assert out_no_fee > out_30 > out_100


def test_v3_in_range_returns_positive() -> None:
    # sqrt(P) ≈ 1.0 → P=1, начальная цена 1:1
    snap = V3PoolSnapshot(
        sqrt_price_x96=Q96,
        liquidity=10**20,
        fee_bps=30,
        decimals0=18,
        decimals1=18,
    )
    out, impact = v3_amount_out_in_range(10**18, snap, zero_for_one=True)
    assert out > 0
    assert math.isfinite(impact)


def test_v3_zero_liquidity_returns_zero() -> None:
    snap = V3PoolSnapshot(sqrt_price_x96=Q96, liquidity=0, fee_bps=30, decimals0=18, decimals1=18)
    out, _ = v3_amount_out_in_range(10**18, snap, zero_for_one=True)
    assert out == 0


def test_whirlpool_in_range_basic() -> None:
    Q64 = 2**64
    out = whirlpool_amount_out_in_range(10**9, Q64, 10**18, 30, zero_for_one=True)
    assert out > 0
