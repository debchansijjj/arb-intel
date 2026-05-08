"""On-chain discovery: подписка на ``PairCreated`` (V2) и ``PoolCreated`` (V3)
по всем factory из registry. Это **главный** источник свежих пулов.
"""

from __future__ import annotations

import asyncio

from arb_intel.bus.streams import Streams, publish
from arb_intel.chains.evm.abis import PAIR_CREATED_TOPIC, POOL_CREATED_TOPIC
from arb_intel.chains.evm.client import EvmChain, build_chain, make_log_stream
from arb_intel.chains.evm.dexes.registry import DexFactory, factories_for
from arb_intel.chains.evm.dexes.v3 import parse_pool_created
from arb_intel.config import get_settings
from arb_intel.logging import get_logger
from arb_intel.utils.metrics import events_seen

log = get_logger(__name__)


async def _watch_factory(chain: EvmChain, fac: DexFactory) -> None:
    topic = POOL_CREATED_TOPIC if fac.kind == "v3" else PAIR_CREATED_TOPIC
    stream = make_log_stream(chain, addresses=[fac.factory], topics=[topic])
    log.info("onchain.factory.watch", chain=chain.name, dex=fac.dex, factory=fac.factory)
    async for ev in stream:
        events_seen.labels(chain=chain.name, kind="pool_created").inc()
        if fac.kind == "v3":
            parsed = parse_pool_created(ev)
            if not parsed:
                continue
            payload = {
                "chain": chain.name,
                "dex": fac.dex,
                "kind": "v3",
                "pool": parsed["pool"],
                "token0": parsed["token0"],
                "token1": parsed["token1"],
                "fee": parsed["fee"],
                "tick_spacing": parsed["tick_spacing"],
                "block": ev.block_number,
                "tx": ev.transaction_hash,
            }
        else:
            # V2 PairCreated: token0/token1 в topics, pair+index в data
            from eth_abi import decode as abi_decode
            from eth_utils import to_bytes

            data = to_bytes(hexstr=ev.data)
            pair, _idx = abi_decode(["address", "uint256"], data)
            payload = {
                "chain": chain.name,
                "dex": fac.dex,
                "kind": "v2",
                "pool": pair.lower(),
                "token0": ("0x" + ev.topics[1][-40:]).lower(),
                "token1": ("0x" + ev.topics[2][-40:]).lower(),
                "fee_bps": fac.default_fee_bps,
                "block": ev.block_number,
                "tx": ev.transaction_hash,
            }
        await publish(Streams.POOL_NEW, payload)


async def run_onchain_discovery() -> None:
    s = get_settings()
    tasks: list[asyncio.Task[None]] = []
    chains_built: list[EvmChain] = []
    try:
        for c in s.chains.enabled:
            if c == "solana":
                continue
            chain = build_chain(c)
            if chain is None or not chain.wss_urls:
                log.warning("onchain.skip_chain", chain=c)
                continue
            chains_built.append(chain)
            for fac in factories_for(c):
                tasks.append(asyncio.create_task(_watch_factory(chain, fac), name=f"onchain:{c}:{fac.dex}"))
        if not tasks:
            log.warning("onchain.no_tasks")
            await asyncio.sleep(60)
            return
        await asyncio.gather(*tasks)
    finally:
        for c in chains_built:
            await c.aclose()
