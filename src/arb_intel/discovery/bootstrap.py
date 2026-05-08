"""Bootstrap pipeline: подтянуть пулы из DexScreener/GeckoTerminal,
нормализовать и положить в Postgres + дать hint в universe-engine.
"""

from __future__ import annotations

import asyncio

from arb_intel.config import get_settings
from arb_intel.db.repositories import upsert_chain, upsert_pool, upsert_token
from arb_intel.db.session import session_scope
from arb_intel.discovery.dexscreener import DexScreener, DexScreenerPair
from arb_intel.discovery.geckoterminal import GeckoPool, GeckoTerminal
from arb_intel.discovery.universe import UniverseEngine, UniverseSignal
from arb_intel.logging import get_logger

log = get_logger(__name__)


_FAMILY = {
    "ethereum": "evm",
    "base": "evm",
    "arbitrum": "evm",
    "bsc": "evm",
    "solana": "solana",
}

_CHAIN_IDS = {"ethereum": 1, "base": 8453, "arbitrum": 42161, "bsc": 56}


def _classify_dex(chain: str, dex: str) -> tuple[str, int]:
    """Возвращает (kind, default_fee_bps)."""
    dex = dex.lower()
    if chain == "solana":
        if "raydium" in dex:
            return "raydium", 25
        if "orca" in dex or "whirlpool" in dex:
            return "whirlpool", 30
        if "meteora" in dex or "dlmm" in dex:
            return "dlmm", 30
        if "pump" in dex:
            return "pumpswap", 30
        return "amm", 30
    if "v3" in dex or "uni3" in dex:
        return "v3", 30
    if "aerodrome" in dex:
        return "aerodrome", 25
    if "v2" in dex or "sushi" in dex or "pancake" in dex or "uniswap" in dex:
        return "v2", 30
    return "v2", 30


async def _persist_dexscreener(pairs: list[DexScreenerPair], universe: UniverseEngine) -> None:
    if not pairs:
        return
    signals: list[UniverseSignal] = []
    async with session_scope() as sess:
        for p in pairs:
            chain = await upsert_chain(
                sess,
                name=p.chain,
                family=_FAMILY.get(p.chain, "evm"),
                chain_id=_CHAIN_IDS.get(p.chain),
            )
            t0 = await upsert_token(
                sess,
                chain_id=chain.id,
                address=p.base_token_address,
                symbol=p.base_symbol,
                name=p.base_symbol,
                decimals=18,  # уточним позже multicall'ом
            )
            t1 = await upsert_token(
                sess,
                chain_id=chain.id,
                address=p.quote_token_address,
                symbol=p.quote_symbol,
                name=p.quote_symbol,
                decimals=18,
                is_stable=(p.quote_symbol or "").upper() in {"USDC", "USDT", "DAI", "FDUSD", "BUSD"},
            )
            kind, fee_bps = _classify_dex(p.chain, p.dex)
            await upsert_pool(
                sess,
                chain_id=chain.id,
                address=p.pair_address,
                dex=p.dex,
                kind=kind,
                token0_id=t0.id,
                token1_id=t1.id,
                fee_bps=fee_bps,
                extra={
                    "ds": {
                        "liq": p.liquidity_usd,
                        "vol24": p.volume_h24_usd,
                        "tx_b": p.txns_h24_buys,
                        "tx_s": p.txns_h24_sells,
                        "px_usd": p.price_usd,
                        "created_ms": p.pair_created_ms,
                    }
                },
            )
            score = 0.0
            if p.liquidity_usd:
                score += min(20.0, p.liquidity_usd / 50_000.0)
            if p.volume_h24_usd:
                score += min(40.0, p.volume_h24_usd / 100_000.0)
            promote = 2 if score >= 20 else 1
            signals.append(
                UniverseSignal(
                    chain=p.chain,
                    token_address=p.base_token_address,
                    score_delta=score,
                    reason="bootstrap:dexscreener",
                    promote_hint=promote,
                )
            )
    await universe.ingest(signals)


async def _persist_gecko(pools: list[GeckoPool], universe: UniverseEngine) -> None:
    if not pools:
        return
    signals: list[UniverseSignal] = []
    async with session_scope() as sess:
        for g in pools:
            chain = await upsert_chain(
                sess,
                name=g.chain,
                family=_FAMILY.get(g.chain, "evm"),
                chain_id=_CHAIN_IDS.get(g.chain),
            )
            t0 = await upsert_token(
                sess, chain_id=chain.id, address=g.base_token_address, symbol=None, name=None, decimals=18
            )
            t1 = await upsert_token(
                sess, chain_id=chain.id, address=g.quote_token_address, symbol=None, name=None, decimals=18
            )
            kind, fee_bps = _classify_dex(g.chain, g.dex)
            await upsert_pool(
                sess,
                chain_id=chain.id,
                address=g.pool_address,
                dex=g.dex,
                kind=kind,
                token0_id=t0.id,
                token1_id=t1.id,
                fee_bps=fee_bps,
                extra={"gt": {"liq": g.reserve_in_usd, "vol24": g.volume_24h_usd}},
            )
            score = 5.0  # gecko trending — стартовый вес
            if g.reserve_in_usd:
                score += min(15.0, g.reserve_in_usd / 50_000)
            signals.append(
                UniverseSignal(
                    chain=g.chain,
                    token_address=g.base_token_address,
                    score_delta=score,
                    reason="bootstrap:gecko",
                    promote_hint=3 if g.pool_created_at else 1,
                )
            )
    await universe.ingest(signals)


async def run_bootstrap_once() -> None:
    s = get_settings()
    chains = s.chains.enabled
    universe = UniverseEngine()
    ds = DexScreener()
    gt = GeckoTerminal()
    try:
        # DexScreener: trending по chain
        ds_pairs: list[DexScreenerPair] = []
        async for p in ds.trending(chains):
            ds_pairs.append(p)
            if len(ds_pairs) >= 1500:
                break
        await _persist_dexscreener(ds_pairs, universe)
        log.info("bootstrap.dexscreener", n=len(ds_pairs))

        # GeckoTerminal: new + trending pools
        gt_pools: list[GeckoPool] = []
        for c in chains:
            for fn in (gt.new_pools, gt.trending):
                try:
                    gt_pools.extend(await fn(c))
                except Exception:
                    log.exception("bootstrap.gecko_fail", chain=c, fn=fn.__name__)
        await _persist_gecko(gt_pools, universe)
        log.info("bootstrap.gecko", n=len(gt_pools))

        await universe.consolidate()
    finally:
        await ds.aclose()
        await gt.aclose()


async def bootstrap_loop() -> None:
    s = get_settings()
    while True:
        try:
            await run_bootstrap_once()
        except Exception:
            log.exception("bootstrap.loop_error")
        await asyncio.sleep(s.discovery.bootstrap_interval_s)
