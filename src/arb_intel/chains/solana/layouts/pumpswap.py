"""PumpSwap (pump.fun AMM) layout.

PumpSwap — простой constant-product AMM с фикс fee ~30 bps. Реальные
балансы храним в vault-аккаунтах (SPL token Account.amount); state-аккаунт
хранит метаданные пары.
"""

from __future__ import annotations

from dataclasses import dataclass

from construct import Bytes, Int8ul, Int16ul, Int64ul, Padding, Struct  # type: ignore[import-untyped]

PUMP_POOL_LAYOUT = Struct(
    Padding(8),
    "poolBump" / Int8ul,
    "index" / Int16ul,
    "creator" / Bytes(32),
    "baseMint" / Bytes(32),
    "quoteMint" / Bytes(32),
    "lpMint" / Bytes(32),
    "poolBaseTokenAccount" / Bytes(32),
    "poolQuoteTokenAccount" / Bytes(32),
    "lpSupply" / Int64ul,
)


@dataclass(slots=True)
class PumpSwapPool:
    base_mint: bytes
    quote_mint: bytes
    base_vault: bytes
    quote_vault: bytes
    lp_supply: int


def parse_pump_pool(data: bytes) -> PumpSwapPool | None:
    if len(data) < 220:
        return None
    try:
        c = PUMP_POOL_LAYOUT.parse(data)
    except Exception:
        return None
    return PumpSwapPool(
        base_mint=bytes(c.baseMint),
        quote_mint=bytes(c.quoteMint),
        base_vault=bytes(c.poolBaseTokenAccount),
        quote_vault=bytes(c.poolQuoteTokenAccount),
        lp_supply=int(c.lpSupply),
    )
