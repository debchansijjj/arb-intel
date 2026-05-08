"""DexScreener API client.

Используется как **bootstrap source** — не как основной канал данных.
Цель: быстро наполнить universe ликвидными парами и периодически
освежать tier-1 (broad). Hot-path работает на on-chain потоках, а не
здесь.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from arb_intel.config import get_settings
from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class DexScreenerPair:
    chain: str
    dex: str
    pair_address: str
    base_token_address: str
    base_symbol: str | None
    quote_token_address: str
    quote_symbol: str | None
    price_usd: float | None
    liquidity_usd: float | None
    volume_h24_usd: float | None
    txns_h24_buys: int | None
    txns_h24_sells: int | None
    pair_created_ms: int | None


_CHAIN_ALIAS = {
    "ethereum": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum",
    "bsc": "bsc",
    "solana": "solana",
}


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_pair(p: dict) -> DexScreenerPair | None:
    chain = (p.get("chainId") or "").lower()
    if chain not in _CHAIN_ALIAS:
        return None
    base = p.get("baseToken") or {}
    quote = p.get("quoteToken") or {}
    liq = p.get("liquidity") or {}
    vol = p.get("volume") or {}
    tx = (p.get("txns") or {}).get("h24") or {}
    return DexScreenerPair(
        chain=_CHAIN_ALIAS[chain],
        dex=(p.get("dexId") or "").lower(),
        pair_address=(p.get("pairAddress") or "").lower(),
        base_token_address=(base.get("address") or "").lower(),
        base_symbol=base.get("symbol"),
        quote_token_address=(quote.get("address") or "").lower(),
        quote_symbol=quote.get("symbol"),
        price_usd=_to_float(p.get("priceUsd")),
        liquidity_usd=_to_float(liq.get("usd")),
        volume_h24_usd=_to_float(vol.get("h24")),
        txns_h24_buys=_to_int(tx.get("buys")),
        txns_h24_sells=_to_int(tx.get("sells")),
        pair_created_ms=_to_int(p.get("pairCreatedAt")),
    )


class DexScreener:
    def __init__(self) -> None:
        s = get_settings()
        self._base = str(s.discovery.dexscreener_base).rstrip("/")
        self._client = httpx.AsyncClient(timeout=8.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
    )
    async def search(self, query: str) -> list[DexScreenerPair]:
        r = await self._client.get(f"{self._base}/dex/search", params={"q": query})
        r.raise_for_status()
        data = r.json()
        out: list[DexScreenerPair] = []
        for p in data.get("pairs") or []:
            parsed = _parse_pair(p)
            if parsed is not None:
                out.append(parsed)
        return out

    @retry(
        reraise=True,
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
    )
    async def pair_by_address(self, chain: str, pair_address: str) -> DexScreenerPair | None:
        r = await self._client.get(f"{self._base}/dex/pairs/{chain}/{pair_address}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs") or data.get("pair") or []
        if isinstance(pairs, dict):
            pairs = [pairs]
        for p in pairs:
            parsed = _parse_pair(p)
            if parsed is not None:
                return parsed
        return None

    async def trending(self, chains: list[str]) -> AsyncIterator[DexScreenerPair]:
        # DexScreener даёт topic-based search; используем популярные тикеры как seed.
        for chain in chains:
            for q in ("WETH", "USDC", "WBTC", "WSOL", "USDT"):
                try:
                    pairs = await self.search(q)
                except Exception:
                    log.exception("dexscreener.search_fail", chain=chain, q=q)
                    continue
                for p in pairs:
                    if p.chain == chain:
                        yield p
