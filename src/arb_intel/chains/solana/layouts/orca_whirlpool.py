"""Orca Whirlpool state.

Полная struct + helpers. Внимание: первые 8 байт аккаунтов Anchor —
discriminator, его пропускаем перед декодом.
"""

from __future__ import annotations

from dataclasses import dataclass

from construct import (  # type: ignore[import-untyped]
    Bytes,
    BytesInteger,
    Int16ul,
    Int32sl,
    Int64ul,
    Struct,
)

# u128 LE — Orca/Anchor сериализует в little-endian.
Uint128ul = BytesInteger(16, swapped=True, signed=False)

WHIRLPOOL_LAYOUT = Struct(
    "whirlpoolsConfig" / Bytes(32),
    "whirlpoolBump" / Bytes(1),
    "tickSpacing" / Int16ul,
    "tickSpacingSeed" / Bytes(2),
    "feeRate" / Int16ul,
    "protocolFeeRate" / Int16ul,
    "liquidity" / Uint128ul,
    "sqrtPrice" / Uint128ul,
    "tickCurrentIndex" / Int32sl,
    "protocolFeeOwedA" / Int64ul,
    "protocolFeeOwedB" / Int64ul,
    "tokenMintA" / Bytes(32),
    "tokenVaultA" / Bytes(32),
    "feeGrowthGlobalA" / Uint128ul,
    "tokenMintB" / Bytes(32),
    "tokenVaultB" / Bytes(32),
    "feeGrowthGlobalB" / Uint128ul,
    "rewardLastUpdatedTimestamp" / Int64ul,
)

ANCHOR_DISCRIMINATOR_LEN = 8


@dataclass(slots=True)
class WhirlpoolState:
    tick_spacing: int
    fee_rate_bps: int        # 10**6 base in Whirlpool; нормализуем → bps
    liquidity: int
    sqrt_price_x64: int      # Whirlpool использует Q64.64
    tick: int
    token_mint_a: bytes
    token_mint_b: bytes
    token_vault_a: bytes
    token_vault_b: bytes


def parse_whirlpool(data: bytes) -> WhirlpoolState | None:
    if len(data) < ANCHOR_DISCRIMINATOR_LEN + 80:
        return None
    try:
        c = WHIRLPOOL_LAYOUT.parse(data[ANCHOR_DISCRIMINATOR_LEN:])
    except Exception:
        return None
    fee_rate_pct = int(c.feeRate) / 1_000_000  # Whirlpool fee in 1e-6
    return WhirlpoolState(
        tick_spacing=int(c.tickSpacing),
        fee_rate_bps=round(fee_rate_pct * 10_000),
        liquidity=int(c.liquidity),
        sqrt_price_x64=int(c.sqrtPrice),
        tick=int(c.tickCurrentIndex),
        token_mint_a=bytes(c.tokenMintA),
        token_mint_b=bytes(c.tokenMintB),
        token_vault_a=bytes(c.tokenVaultA),
        token_vault_b=bytes(c.tokenVaultB),
    )


# ---------------- math ----------------
Q64 = 2**64


def price_from_sqrt_x64(sqrt_price_x64: int, decimals_a: int, decimals_b: int) -> float:
    if sqrt_price_x64 == 0:
        return 0.0
    p = (sqrt_price_x64 / Q64) ** 2
    # token b per token a, normalised
    return p * (10**decimals_a) / (10**decimals_b)
