"""Arbitrage scanner.

Запускает несколько режимов:
- ``StateDeltaScanner``  — реактивно: на каждом state-delta пула ищем
  лучший контр-пул в hot-state и считаем спред.
- ``LaggingScanner``     — потребляет ``OPP_CANDIDATE`` от lag_detector,
  обогащает симуляцией.
- ``CrossChainScanner``  — кросс-чейн перебор по той же базе токенов
  (через canonical address mapping; для известных wrapped — есть
  registry).
- ``FreshPoolScanner``   — реакция на ``POOL_NEW``: даём пулу 30s
  прогреться, затем ищем расхождение с уже существующим пулом по той
  же паре.

Все обнаруженные кандидаты попадают в pipeline:
  scanner → simulator → heuristics → scoring → alert.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

from arb_intel.bus.streams import Streams, consume, publish
from arb_intel.config import get_settings
from arb_intel.logging import get_logger
from arb_intel.tracking.pool_state import HotPoolState, iter_all, read
from arb_intel.utils.metrics import opportunities_found

log = get_logger(__name__)


@dataclass(slots=True)
class Candidate:
    chain_buy: str
    chain_sell: str
    buy_pool: str
    sell_pool: str
    base_token: str
    quote_token: str
    spread_bps: float
    kind: str           # "intra-dex" | "cross-dex" | "cross-chain" | "lagging" | "fresh"
    leader_pool: str | None = None
    fresh: bool = False


def _norm_pair(p: HotPoolState) -> tuple[str, str]:
    return tuple(sorted([p.token0, p.token1]))


def _is_same_pair(a: HotPoolState, b: HotPoolState) -> bool:
    return _norm_pair(a) == _norm_pair(b)


def _spread_bps(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return abs(a - b) / max(a, b) * 10_000


# Canonical token mappings для cross-chain эвристики (упрощённо, базовые).
# В проде это must-be-config / DB-таблица.
CANONICAL_TOKEN_GROUPS: list[set[tuple[str, str]]] = [
    # WETH / ETH
    {("ethereum", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"),
     ("base", "0x4200000000000000000000000000000000000006"),
     ("arbitrum", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1")},
    # USDC
    {("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
     ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),
     ("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"),
     ("solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")},
    # USDT
    {("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7"),
     ("base", "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2"),
     ("arbitrum", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"),
     ("solana", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")},
    # WBTC
    {("ethereum", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"),
     ("base", "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"),
     ("arbitrum", "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f")},
]


def canonical_group(chain: str, token: str) -> set[tuple[str, str]] | None:
    key = (chain, token.lower())
    for grp in CANONICAL_TOKEN_GROUPS:
        if key in grp:
            return grp
    return None


# ---------------- intra/cross-dex on same chain ----------------
class StateDeltaScanner:
    def __init__(self) -> None:
        s = get_settings()
        self._min_spread_bps = s.arb.min_spread_bps

    async def on_state(self, payload: dict) -> None:
        chain = payload["chain"]
        pool = payload["pool"]
        state = await read(chain, pool)
        if state is None or state.implied_price <= 0:
            return
        # ищем все пулы той же пары на том же чейне (cross-DEX) + cross-chain
        groups: dict[tuple[str, str], list[HotPoolState]] = defaultdict(list)
        async for other in iter_all():
            if not _is_same_pair(other, state):
                continue
            groups[(other.chain, str(_norm_pair(other)))].append(other)

        cands: list[Candidate] = []
        for _key, pools in groups.items():
            if len(pools) < 2:
                continue
            # внутри одной chain ищем самые крайние по implied_price
            pools_sorted = sorted(pools, key=lambda p: p.implied_price)
            cheap = pools_sorted[0]
            expensive = pools_sorted[-1]
            if cheap.pool == expensive.pool:
                continue
            spread = _spread_bps(cheap.implied_price, expensive.implied_price)
            if spread < self._min_spread_bps:
                continue
            cands.append(Candidate(
                chain_buy=cheap.chain, chain_sell=expensive.chain,
                buy_pool=cheap.pool, sell_pool=expensive.pool,
                base_token=cheap.token0, quote_token=cheap.token1,
                spread_bps=spread,
                kind="cross-dex" if cheap.dex != expensive.dex else "intra-dex",
            ))

        for c in cands:
            opportunities_found.labels(kind=c.kind).inc()
            await publish(Streams.OPP_CANDIDATE, _to_payload(c))


def _to_payload(c: Candidate) -> dict:
    return {
        "kind": c.kind,
        "chain_buy": c.chain_buy,
        "chain_sell": c.chain_sell,
        "buy_pool": c.buy_pool,
        "sell_pool": c.sell_pool,
        "base_token": c.base_token,
        "quote_token": c.quote_token,
        "spread_bps": c.spread_bps,
        "fresh": c.fresh,
        "leader_pool": c.leader_pool,
        "ts": time.time(),
    }


async def run_state_delta_scanner() -> None:
    scanner = StateDeltaScanner()
    async for msg in consume(Streams.POOL_STATE, group="state-scanner", consumer="ss-1"):
        try:
            await scanner.on_state(msg.payload)
        except Exception:
            log.exception("state_scanner.error")


# ---------------- cross-chain pass ----------------
async def run_cross_chain_loop() -> None:
    """Периодический полный обход: ищем спреды между chain'ами для
    canonical-токенов. Не зависит от потока state — стабильный fallback."""
    s = get_settings()
    while True:
        try:
            # сгруппировать пулы по (canonical-base, canonical-quote)
            buckets: dict[tuple[frozenset, frozenset], list[HotPoolState]] = defaultdict(list)
            async for p in iter_all():
                gb = canonical_group(p.chain, p.token0) or {(p.chain, p.token0)}
                gq = canonical_group(p.chain, p.token1) or {(p.chain, p.token1)}
                buckets[(frozenset(gb), frozenset(gq))].append(p)

            cands: list[Candidate] = []
            for (_gb, _gq), pools in buckets.items():
                if len(pools) < 2:
                    continue
                pools_sorted = sorted(pools, key=lambda p: p.implied_price)
                cheap = pools_sorted[0]
                expensive = pools_sorted[-1]
                if cheap.chain == expensive.chain:
                    continue
                if cheap.implied_price <= 0:
                    continue
                spread = _spread_bps(cheap.implied_price, expensive.implied_price)
                if spread < s.arb.min_spread_bps:
                    continue
                cands.append(Candidate(
                    chain_buy=cheap.chain, chain_sell=expensive.chain,
                    buy_pool=cheap.pool, sell_pool=expensive.pool,
                    base_token=cheap.token0, quote_token=cheap.token1,
                    spread_bps=spread, kind="cross-chain",
                ))
            for c in cands:
                opportunities_found.labels(kind=c.kind).inc()
                await publish(Streams.OPP_CANDIDATE, _to_payload(c))
        except Exception:
            log.exception("cross_chain_scanner.error")
        await asyncio.sleep(s.arb.scanner_interval_s)


# ---------------- fresh pool ----------------
async def run_fresh_pool_loop() -> None:
    s = get_settings()
    async for msg in consume(Streams.POOL_NEW, group="fresh-scanner", consumer="fs-1"):
        try:
            chain = msg.payload["chain"]
            pool = msg.payload["pool"]
            await asyncio.sleep(s.arb.fresh_warmup_s)
            new_state = await read(chain, pool)
            if new_state is None or new_state.implied_price <= 0:
                continue
            async for other in iter_all(chain):
                if other.pool == pool:
                    continue
                if not _is_same_pair(other, new_state):
                    continue
                spread = _spread_bps(new_state.implied_price, other.implied_price)
                if spread < s.arb.min_spread_bps:
                    continue
                cheap, expensive = (new_state, other) if new_state.implied_price < other.implied_price else (other, new_state)
                cand = Candidate(
                    chain_buy=cheap.chain, chain_sell=expensive.chain,
                    buy_pool=cheap.pool, sell_pool=expensive.pool,
                    base_token=cheap.token0, quote_token=cheap.token1,
                    spread_bps=spread, kind="fresh", fresh=True,
                )
                opportunities_found.labels(kind="fresh").inc()
                await publish(Streams.OPP_CANDIDATE, _to_payload(cand))
        except Exception:
            log.exception("fresh_scanner.error")
