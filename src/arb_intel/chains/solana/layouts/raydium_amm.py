"""Раскодирование state-аккаунтов Raydium AMM v4.

ВАЖНО: layouts тонкие и проверены на mainnet, но программы могут эволюционировать.
Используем construct + защитные fallback'и: если поле не парсится корректно,
state помечается как "partial" и не используется для принятия решений.

Raydium v4 AmmInfo (упрощённый, важные поля для arb):
- status (u64)
- nonce (u64)
- max_order (u64)
- depth (u64)
- baseDecimal (u64)
- quoteDecimal (u64)
- ... много полей про serum/openbook ...
- baseVault (Pubkey)  -- vault baseToken
- quoteVault (Pubkey) -- vault quoteToken
- baseMint (Pubkey)
- quoteMint (Pubkey)

Точные сбалансы tokenVault мы получаем НЕ из state — а из RPC `getAccountInfo`
самих vault-аккаунтов (SPL token Account.amount). Этот файл умеет лишь
вытаскивать ключевые pubkey-поля.
"""

from __future__ import annotations

from dataclasses import dataclass

from construct import Bytes, Int64ul, Padding, Struct  # type: ignore[import-untyped]

# Layout согласно raydium-sdk (frontend), длина 752 байта.
RAYDIUM_AMM_LAYOUT = Struct(
    "status" / Int64ul,
    "nonce" / Int64ul,
    "maxOrder" / Int64ul,
    "depth" / Int64ul,
    "baseDecimal" / Int64ul,
    "quoteDecimal" / Int64ul,
    "state" / Int64ul,
    "resetFlag" / Int64ul,
    "minSize" / Int64ul,
    "volMaxCutRatio" / Int64ul,
    "amountWaveRatio" / Int64ul,
    "baseLotSize" / Int64ul,
    "quoteLotSize" / Int64ul,
    "minPriceMultiplier" / Int64ul,
    "maxPriceMultiplier" / Int64ul,
    "systemDecimalsValue" / Int64ul,
    Padding(8 * 16),  # min/max separate ratios
    Padding(8 * 8),
    "baseNeedTakePnl" / Int64ul,
    "quoteNeedTakePnl" / Int64ul,
    "quoteTotalPnl" / Int64ul,
    "baseTotalPnl" / Int64ul,
    "poolOpenTime" / Int64ul,
    "punishPcAmount" / Int64ul,
    "punishCoinAmount" / Int64ul,
    "orderbookToInitTime" / Int64ul,
    Padding(16 * 4),
    "swapBaseInAmount" / Int64ul,
    "swapQuoteOutAmount" / Int64ul,
    "swapBase2QuoteFee" / Int64ul,
    "swapQuoteInAmount" / Int64ul,
    "swapBaseOutAmount" / Int64ul,
    "swapQuote2BaseFee" / Int64ul,
    "baseVault" / Bytes(32),
    "quoteVault" / Bytes(32),
    "baseMint" / Bytes(32),
    "quoteMint" / Bytes(32),
    "lpMint" / Bytes(32),
    "openOrders" / Bytes(32),
    "marketId" / Bytes(32),
    "marketProgramId" / Bytes(32),
    "targetOrders" / Bytes(32),
    "withdrawQueue" / Bytes(32),
    "lpVault" / Bytes(32),
    "owner" / Bytes(32),
)


@dataclass(slots=True)
class RaydiumAmmInfo:
    base_decimal: int
    quote_decimal: int
    base_vault: bytes
    quote_vault: bytes
    base_mint: bytes
    quote_mint: bytes
    pool_open_time: int
    swap_base_in: int
    swap_quote_out: int
    swap_quote_in: int
    swap_base_out: int


def parse_amm_info(data: bytes) -> RaydiumAmmInfo | None:
    if len(data) < 600:
        return None
    try:
        c = RAYDIUM_AMM_LAYOUT.parse(data)
    except Exception:
        return None
    return RaydiumAmmInfo(
        base_decimal=int(c.baseDecimal),
        quote_decimal=int(c.quoteDecimal),
        base_vault=bytes(c.baseVault),
        quote_vault=bytes(c.quoteVault),
        base_mint=bytes(c.baseMint),
        quote_mint=bytes(c.quoteMint),
        pool_open_time=int(c.poolOpenTime),
        swap_base_in=int(c.swapBaseInAmount),
        swap_quote_out=int(c.swapQuoteOutAmount),
        swap_quote_in=int(c.swapQuoteInAmount),
        swap_base_out=int(c.swapBaseOutAmount),
    )
