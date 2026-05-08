"""GeckoTerminal API client.

Дополняет DexScreener: иногда лучше покрывает только что появившиеся
пулы (`new_pools`). Используем как secondary bootstrap.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from arb_intel.config import get_settings

_CHAIN_TO_NETWORK = {
    "ethereum": "eth",
    "base": "base",
    "arbitrum": "arbitrum",
    "bsc": "bsc",
    "solana": "solana",
}


@dataclass(slots=True)
class GeckoPool:
    chain: str
    dex: str
    pool_address: str
    base_token_address: str
    quote_token_address: str
    reserve_in_usd: float | None
    volume_24h_usd: float | None
    pool_created_at: str | None


class GeckoTerminal:
    def __init__(self) -> None:
        s = get_settings()
        self._base = str(s.discovery.geckoterminal_base).rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0, headers={"accept": "application/json"})

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
    )
    async def new_pools(self, chain: str, *, page: int = 1) -> list[GeckoPool]:
        net = _CHAIN_TO_NETWORK.get(chain)
        if not net:
            return []
        r = await self._client.get(f"{self._base}/networks/{net}/new_pools", params={"page": page})
        r.raise_for_status()
        body = r.json()
        out: list[GeckoPool] = []
        for d in body.get("data", []):
            attrs = d.get("attributes") or {}
            rels = d.get("relationships") or {}
            base = (rels.get("base_token") or {}).get("data") or {}
            quote = (rels.get("quote_token") or {}).get("data") or {}
            base_addr = (base.get("id") or "").split("_", 1)[-1]
            quote_addr = (quote.get("id") or "").split("_", 1)[-1]
            out.append(
                GeckoPool(
                    chain=chain,
                    dex=(attrs.get("dex_id") or "").lower(),
                    pool_address=(attrs.get("address") or "").lower(),
                    base_token_address=base_addr.lower(),
                    quote_token_address=quote_addr.lower(),
                    reserve_in_usd=_to_float(attrs.get("reserve_in_usd")),
                    volume_24h_usd=_to_float((attrs.get("volume_usd") or {}).get("h24")),
                    pool_created_at=attrs.get("pool_created_at"),
                )
            )
        return out

    @retry(
        reraise=True,
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
    )
    async def trending(self, chain: str) -> list[GeckoPool]:
        net = _CHAIN_TO_NETWORK.get(chain)
        if not net:
            return []
        r = await self._client.get(f"{self._base}/networks/{net}/trending_pools")
        r.raise_for_status()
        body = r.json()
        out: list[GeckoPool] = []
        for d in body.get("data", []):
            attrs = d.get("attributes") or {}
            rels = d.get("relationships") or {}
            base = (rels.get("base_token") or {}).get("data") or {}
            quote = (rels.get("quote_token") or {}).get("data") or {}
            out.append(
                GeckoPool(
                    chain=chain,
                    dex=(attrs.get("dex_id") or "").lower(),
                    pool_address=(attrs.get("address") or "").lower(),
                    base_token_address=((base.get("id") or "").split("_", 1)[-1]).lower(),
                    quote_token_address=((quote.get("id") or "").split("_", 1)[-1]).lower(),
                    reserve_in_usd=_to_float(attrs.get("reserve_in_usd")),
                    volume_24h_usd=_to_float((attrs.get("volume_usd") or {}).get("h24")),
                    pool_created_at=attrs.get("pool_created_at"),
                )
            )
        return out


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
