"""SPL Token Account layout (для чтения баланса vault'ов)."""

from __future__ import annotations

from dataclasses import dataclass

from construct import Bytes, Int8ul, Int64ul, Padding, Struct  # type: ignore[import-untyped]

# 165 bytes
TOKEN_ACCOUNT = Struct(
    "mint" / Bytes(32),
    "owner" / Bytes(32),
    "amount" / Int64ul,
    "delegateOption" / Int8ul,
    Padding(3),
    "delegate" / Bytes(32),
    "state" / Int8ul,
    "isNativeOption" / Int8ul,
    Padding(3),
    "isNative" / Int64ul,
    "delegatedAmount" / Int64ul,
    "closeAuthorityOption" / Int8ul,
    Padding(3),
    "closeAuthority" / Bytes(32),
)


# 82 bytes
MINT_ACCOUNT = Struct(
    "mintAuthorityOption" / Int8ul,
    Padding(3),
    "mintAuthority" / Bytes(32),
    "supply" / Int64ul,
    "decimals" / Int8ul,
    "isInitialized" / Int8ul,
    "freezeAuthorityOption" / Int8ul,
    Padding(3),
    "freezeAuthority" / Bytes(32),
)


@dataclass(slots=True)
class TokenAccountInfo:
    mint: bytes
    owner: bytes
    amount: int


@dataclass(slots=True)
class MintInfo:
    decimals: int
    supply: int


def parse_token_account(data: bytes) -> TokenAccountInfo | None:
    if len(data) < 165:
        return None
    try:
        c = TOKEN_ACCOUNT.parse(data[:165])
    except Exception:
        return None
    return TokenAccountInfo(mint=bytes(c.mint), owner=bytes(c.owner), amount=int(c.amount))


def parse_mint(data: bytes) -> MintInfo | None:
    if len(data) < 82:
        return None
    try:
        c = MINT_ACCOUNT.parse(data[:82])
    except Exception:
        return None
    return MintInfo(decimals=int(c.decimals), supply=int(c.supply))
