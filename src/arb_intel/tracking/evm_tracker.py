"""EVM tracker: ловит V2 ``Sync`` / V3 ``Swap`` логи и обновляет hot pool state.

Адаптер работает в двух режимах:
1. **WS-режим**: подписываемся на ``logs`` без фильтра по адресам — это
   быстрее всего, но требует ``addresses`` фильтр на крупных сетях,
   иначе нас зальёт. Поэтому используем фильтр по topic + подписываемся
   по chunk-ам пулов из universe.
2. **Refresh-режим**: периодически (каждые ``refresh_interval_s``)
   подтягиваем reserves/slot0 у всех известных пулов через multicall —
   ловим то, что могли пропустить (reorg, gap).

Узнаём `decimals` лениво при первом обращении и кэшируем в Redis.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from sqlalchemy import select

from arb_intel.bus.streams import Streams, publish
from arb_intel.chains.evm.abis import SYNC_TOPIC, V2_SWAP_TOPIC, V3_SWAP_TOPIC
from arb_intel.chains.evm.client import EvmChain, build_chain, make_log_stream
from arb_intel.chains.evm.dexes.erc20 import fetch_metadata
from arb_intel.chains.evm.dexes.v2 import fetch_reserves, parse_sync
from arb_intel.chains.evm.dexes.v2 import parse_swap as parse_v2_swap
from arb_intel.chains.evm.dexes.v3 import V3State, fetch_state
from arb_intel.chains.evm.dexes.v3 import parse_swap as parse_v3_swap
from arb_intel.config import get_settings
from arb_intel.db.models import Chain, Pool, Token
from arb_intel.db.session import session_scope
from arb_intel.logging import get_logger
from arb_intel.tracking.liquidity import update_v2, update_v3

log = get_logger(__name__)

CHUNK = 200


async def _load_pools_for_chain(chain_name: str) -> list[dict]:
    async with session_scope() as sess:
        chain_row = (await sess.execute(select(Chain).where(Chain.name == chain_name))).scalar_one_or_none()
        if chain_row is None:
            return []
        rows = (
            await sess.execute(
                select(Pool, Token, Token).join(Token, Token.id == Pool.token0_id).join(
                    Token, Token.id == Pool.token1_id, isouter=False
                ).where(Pool.chain_id == chain_row.id)
            )
        ).all()
    return [
        {
            "pool": r[0].address.lower(),
            "dex": r[0].dex,
            "kind": r[0].kind,
            "fee_bps": r[0].fee_bps,
            "token0": r[1].address.lower(),
            "token1": r[2].address.lower(),
            "decimals0": r[1].decimals or 18,
            "decimals1": r[2].decimals or 18,
        }
        for r in rows
    ]


def _index_by_pool(rows: list[dict]) -> dict[str, dict]:
    return {r["pool"]: r for r in rows}


async def _enrich_decimals(chain: EvmChain, rows: list[dict]) -> None:
    missing: list[str] = []
    for r in rows:
        if not r.get("decimals0") or r["decimals0"] == 18:
            missing.append(r["token0"])
        if not r.get("decimals1") or r["decimals1"] == 18:
            missing.append(r["token1"])
    if not missing:
        return
    metas = await fetch_metadata(chain.rpc, list(set(missing)))
    if not metas:
        return
    async with session_scope() as sess:
        chain_row = (await sess.execute(select(Chain).where(Chain.name == chain.name))).scalar_one_or_none()
        if chain_row is None:
            return
        for addr, m in metas.items():
            tok = (
                await sess.execute(
                    select(Token).where(Token.chain_id == chain_row.id, Token.address == addr.lower())
                )
            ).scalar_one_or_none()
            if tok is None:
                continue
            tok.decimals = m.decimals
            tok.symbol = m.symbol or tok.symbol
            tok.name = m.name or tok.name


_TAIL_TASKS: set[asyncio.Task] = set()


async def _tail_logs_v2(chain: EvmChain, pools_index: dict[str, dict]) -> None:
    if not pools_index:
        return
    addrs = list(pools_index.keys())
    # WS subscription по chunk-ам
    for i in range(0, len(addrs), CHUNK):
        chunk = addrs[i : i + CHUNK]
        task = asyncio.create_task(
            _run_v2_chunk(chain, chunk, pools_index), name=f"v2tail:{chain.name}:{i}"
        )
        _TAIL_TASKS.add(task)
        task.add_done_callback(_TAIL_TASKS.discard)


async def _run_v2_chunk(chain: EvmChain, addrs: Iterable[str], pools_index: dict[str, dict]) -> None:
    stream = make_log_stream(chain, addresses=list(addrs), topics=[[SYNC_TOPIC, V2_SWAP_TOPIC]])
    async for ev in stream:
        meta = pools_index.get(ev.address)
        if not meta:
            continue
        if ev.topics and ev.topics[0].lower() == SYNC_TOPIC:
            st = parse_sync(ev)
            if not st:
                continue
            await update_v2(
                chain.name, ev.address, meta["dex"], meta["fee_bps"],
                meta["token0"], meta["token1"], meta["decimals0"], meta["decimals1"], st,
            )
        elif ev.topics and ev.topics[0].lower() == V2_SWAP_TOPIC:
            sw = parse_v2_swap(ev)
            if not sw:
                continue
            await publish(Streams.SWAP, {
                "chain": chain.name, "pool": ev.address, "kind": "v2",
                "amount0_in": sw.amount0_in, "amount1_in": sw.amount1_in,
                "amount0_out": sw.amount0_out, "amount1_out": sw.amount1_out,
                "block": sw.block_number, "tx": sw.tx_hash,
            })


async def _run_v3_chunk(chain: EvmChain, addrs: Iterable[str], pools_index: dict[str, dict]) -> None:
    stream = make_log_stream(chain, addresses=list(addrs), topics=[V3_SWAP_TOPIC])
    async for ev in stream:
        meta = pools_index.get(ev.address)
        if not meta:
            continue
        sw = parse_v3_swap(ev)
        if sw is None:
            continue
        st = V3State(
            pool=ev.address,
            sqrt_price_x96=sw.sqrt_price_x96,
            tick=sw.tick,
            liquidity=sw.liquidity,
            block_number=sw.block_number,
        )
        await update_v3(
            chain.name, ev.address, meta["dex"], meta["fee_bps"],
            meta["token0"], meta["token1"], meta["decimals0"], meta["decimals1"], st,
        )
        await publish(Streams.SWAP, {
            "chain": chain.name, "pool": ev.address, "kind": "v3",
            "amount0": sw.amount0, "amount1": sw.amount1,
            "block": sw.block_number, "tx": sw.tx_hash,
        })


async def _refresh_loop(chain: EvmChain, pools_index: dict[str, dict]) -> None:
    s = get_settings()
    interval = s.arb.refresh_interval_s
    while True:
        try:
            v2 = [p for p, m in pools_index.items() if m["kind"] in ("v2", "aerodrome")]
            v3 = [p for p, m in pools_index.items() if m["kind"] in ("v3",)]
            for i in range(0, len(v2), CHUNK):
                chunk = v2[i : i + CHUNK]
                states = await fetch_reserves(chain.rpc, chunk)
                for pool, st in states.items():
                    meta = pools_index.get(pool)
                    if not meta:
                        continue
                    await update_v2(
                        chain.name, pool, meta["dex"], meta["fee_bps"],
                        meta["token0"], meta["token1"],
                        meta["decimals0"], meta["decimals1"], st, source="multicall",
                    )
            for i in range(0, len(v3), CHUNK):
                chunk = v3[i : i + CHUNK]
                states = await fetch_state(chain.rpc, chunk)
                for pool, st in states.items():
                    meta = pools_index.get(pool)
                    if not meta:
                        continue
                    await update_v3(
                        chain.name, pool, meta["dex"], meta["fee_bps"],
                        meta["token0"], meta["token1"],
                        meta["decimals0"], meta["decimals1"], st, source="multicall",
                    )
        except Exception:
            log.exception("evm_tracker.refresh_error", chain=chain.name)
        await asyncio.sleep(interval)


async def run_evm_tracker(chain_name: str) -> None:
    chain = build_chain(chain_name)
    if chain is None:
        log.warning("evm_tracker.skip", chain=chain_name)
        return
    try:
        rows = await _load_pools_for_chain(chain_name)
        if not rows:
            log.warning("evm_tracker.no_pools", chain=chain_name)
            await asyncio.sleep(60)
            return
        await _enrich_decimals(chain, rows)
        # Перечитаем после enrich
        rows = await _load_pools_for_chain(chain_name)
        idx = _index_by_pool(rows)
        log.info("evm_tracker.start", chain=chain_name, pools=len(rows))
        await _tail_logs_v2(chain, idx)  # схлопываем v2/v3 в одном tail (один топик-фильтр на чанк)
        await _refresh_loop(chain, idx)
    finally:
        await chain.aclose()
