"""Точная decimal-математика для денег.

Не используем float напрямую в hot-path кроме скоринга — для P&L и сумм
работаем в Decimal с фиксированной точностью.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

# 50 digits — достаточно для price * size * fees * decimals в самых ужасных
# сценариях (decimals=18 на обоих токенах + 6 знаков для USD).
getcontext().prec = 50

ZERO = Decimal(0)
ONE = Decimal(1)
BPS = Decimal(10000)


def from_raw(amount: int, decimals: int) -> Decimal:
    if decimals == 0:
        return Decimal(amount)
    return Decimal(amount) / (Decimal(10) ** decimals)


def to_raw(amount: Decimal, decimals: int) -> int:
    return int((amount * (Decimal(10) ** decimals)).to_integral_value())


def bps(value: Decimal) -> Decimal:
    return value * BPS


def from_bps(value: Decimal | int | float) -> Decimal:
    return Decimal(value) / BPS
