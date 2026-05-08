"""Meteora DLMM (Dynamic Liquidity Market Maker) lb-pair state.

Полный layout DLMM большой (bin-array отдельно). Здесь — только
шапка LbPair с активным bin'ом и параметрами для implied-price.

bin price = (1 + bin_step / 10000) ** active_id
"""

from __future__ import annotations

from dataclasses import dataclass

from construct import (  # type: ignore[import-untyped]
    Bytes,
    Int8ul,
    Int16ul,
    Int32sl,
    Int64ul,
    Padding,
    Struct,
)

# Урезанный layout — нам нужен active_id, bin_step, mint-ы и vaults.
LB_PAIR_LAYOUT = Struct(
    Padding(8),  # discriminator
    "parameters_baseFactor" / Int16ul,
    "parameters_filterPeriod" / Int16ul,
    "parameters_decayPeriod" / Int16ul,
    "parameters_reductionFactor" / Int16ul,
    "parameters_variableFeeControl" / Int32sl,
    "parameters_maxVolatilityAccumulator" / Int32sl,
    "parameters_minBinId" / Int32sl,
    "parameters_maxBinId" / Int32sl,
    "parameters_protocolShare" / Int16ul,
    Padding(2),
    "vParameters_volatilityAccumulator" / Int32sl,
    "vParameters_volatilityReference" / Int32sl,
    "vParameters_indexReference" / Int32sl,
    Padding(4),
    "vParameters_lastUpdateTimestamp" / Int64ul,
    Padding(8),
    "bumpSeed" / Bytes(1),
    "binStepSeed" / Bytes(2),
    "pairType" / Int8ul,
    "activeId" / Int32sl,
    "binStep" / Int16ul,
    "status" / Int8ul,
    Padding(5),
    "tokenXMint" / Bytes(32),
    "tokenYMint" / Bytes(32),
    "reserveX" / Bytes(32),
    "reserveY" / Bytes(32),
)


@dataclass(slots=True)
class LbPairState:
    active_id: int
    bin_step: int
    token_x_mint: bytes
    token_y_mint: bytes
    reserve_x_account: bytes
    reserve_y_account: bytes


def parse_lb_pair(data: bytes) -> LbPairState | None:
    if len(data) < 200:
        return None
    try:
        c = LB_PAIR_LAYOUT.parse(data)
    except Exception:
        return None
    return LbPairState(
        active_id=int(c.activeId),
        bin_step=int(c.binStep),
        token_x_mint=bytes(c.tokenXMint),
        token_y_mint=bytes(c.tokenYMint),
        reserve_x_account=bytes(c.reserveX),
        reserve_y_account=bytes(c.reserveY),
    )


def implied_price(active_id: int, bin_step_bps: int, decimals_x: int, decimals_y: int) -> float:
    # price y/x = (1 + bin_step/10000) ** active_id
    base = 1.0 + bin_step_bps / 10_000
    raw = base**active_id
    return raw * (10**decimals_x) / (10**decimals_y)
