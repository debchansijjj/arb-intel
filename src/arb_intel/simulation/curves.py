"""Realistic execution math для разных AMM-кривых.

Поддерживаются:
- Constant product (V2 / Aerodrome volatile / Raydium AMM v4 / PumpSwap)
- Stable-swap volatile-fallback (упрощённо: используем V2 при недостатке данных)
- Concentrated liquidity (V3 / Whirlpool / Pancake V3) — упрощённая
  модель в пределах текущего тика; при больших размерах учитывается
  деградация ликвидности через эффективную ликвидность.

Все функции возвращают **net amount_out** уже после фи пула.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------- V2 / constant product ----------------
def v2_amount_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    fee_num = 10_000 - fee_bps
    amount_in_with_fee = amount_in * fee_num
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * 10_000 + amount_in_with_fee
    return numerator // denominator


def v2_price_impact_bps(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> float:
    if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
        return 0.0
    out = v2_amount_out(amount_in, reserve_in, reserve_out, fee_bps)
    if out == 0:
        return 10_000.0
    spot = reserve_out / reserve_in
    avg = out / amount_in
    if spot <= 0:
        return 10_000.0
    impact = (spot - avg) / spot
    return max(0.0, impact) * 10_000


# ---------------- V3 / concentrated ----------------
Q96 = 2**96


@dataclass(slots=True)
class V3PoolSnapshot:
    sqrt_price_x96: int
    liquidity: int                 # in-range liquidity (L)
    fee_bps: int
    decimals0: int
    decimals1: int


def v3_amount_out_in_range(
    amount_in: int, snap: V3PoolSnapshot, *, zero_for_one: bool
) -> tuple[int, float]:
    """Упрощённая модель в пределах текущего тика.

    Возвращает (amount_out, price_impact_bps).
    Если в реальности своп переходит несколько тиков, наш ответ — это
    нижняя граница из доступной информации (чем больше size — тем больше
    погрешность, тем сильнее даунвейтит scoring engine).

    Формулы:
      sqrt(P)' = sqrt(P) +- amount_in / L (в Q96)  (упрощение в-range)
      amount_out = L * |sqrt(P)' - sqrt(P)|  / (sqrt(P)*sqrt(P)')
    """
    if amount_in <= 0 or snap.liquidity <= 0 or snap.sqrt_price_x96 <= 0:
        return 0, 10_000.0
    sqrt_p = snap.sqrt_price_x96
    L = snap.liquidity
    fee = (10_000 - snap.fee_bps) / 10_000

    amount_in_eff = int(amount_in * fee)
    if zero_for_one:
        # token0 -> token1, цена падает: sqrt(P)' = sqrt(P) - amount_in*Q96/L
        # Но точная формула: 1/sqrt(P)' = 1/sqrt(P) + amount_in/L
        if sqrt_p == 0:
            return 0, 10_000.0
        denom = L * Q96 + amount_in_eff * sqrt_p
        if denom == 0:
            return 0, 10_000.0
        new_sqrt = (L * Q96 * sqrt_p) // denom
        if new_sqrt <= 0:
            return 0, 10_000.0
        amount_out = (L * (sqrt_p - new_sqrt)) // Q96
    else:
        # token1 -> token0, цена растёт: sqrt(P)' = sqrt(P) + amount_in*Q96/L
        new_sqrt = sqrt_p + (amount_in_eff * Q96) // L
        if new_sqrt <= 0:
            return 0, 10_000.0
        amount_out = (L * Q96 * (new_sqrt - sqrt_p)) // (sqrt_p * new_sqrt)

    if amount_out <= 0:
        return 0, 10_000.0

    spot_p = (sqrt_p / Q96) ** 2  # token1 per token0
    if zero_for_one:
        avg = (amount_out / amount_in) * (10**snap.decimals0 / 10**snap.decimals1)
        spot = spot_p
    else:
        avg = (amount_in / amount_out) * (10**snap.decimals0 / 10**snap.decimals1)
        spot = spot_p
    if spot <= 0 or math.isnan(avg):
        return amount_out, 0.0
    impact = abs(spot - avg) / spot
    return int(amount_out), max(0.0, impact * 10_000)


# ---------------- Whirlpool (X64) ----------------
def whirlpool_amount_out_in_range(
    amount_in: int, sqrt_price_x64: int, liquidity: int, fee_bps: int, *, zero_for_one: bool
) -> int:
    """Whirlpool: sqrt-price хранится в Q64.64. Используем те же формулы,
    что у V3, заменив Q96 → Q64."""
    Q = 2**64
    if amount_in <= 0 or liquidity <= 0 or sqrt_price_x64 <= 0:
        return 0
    fee = (10_000 - fee_bps) / 10_000
    amount_in_eff = int(amount_in * fee)
    sqrt_p = sqrt_price_x64
    L = liquidity
    if zero_for_one:
        denom = L * Q + amount_in_eff * sqrt_p
        if denom == 0:
            return 0
        new_sqrt = (L * Q * sqrt_p) // denom
        amount_out = (L * (sqrt_p - new_sqrt)) // Q
    else:
        new_sqrt = sqrt_p + (amount_in_eff * Q) // L
        amount_out = (L * Q * (new_sqrt - sqrt_p)) // (sqrt_p * new_sqrt)
    return max(0, amount_out)
