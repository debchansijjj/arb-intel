"""Высокоуровневый EVM-клиент: rpc-pool + ws-stream + helpers."""

from __future__ import annotations

from dataclasses import dataclass

from arb_intel.chains.evm.rpc import JsonRpcPool
from arb_intel.chains.evm.ws import EvmLogStream
from arb_intel.config import EvmChainEndpoint, get_settings
from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class EvmChain:
    name: str
    chain_id: int
    rpc: JsonRpcPool
    wss_urls: list[str]

    async def aclose(self) -> None:
        await self.rpc.aclose()


def build_chain(name: str) -> EvmChain | None:
    s = get_settings()
    cfg: EvmChainEndpoint | None = s.evm.by_name(name)
    if cfg is None or not cfg.https:
        log.warning("evm.no_config", chain=name)
        return None
    rpc = JsonRpcPool(cfg.https, name=name)
    chain_id = cfg.chain_id or _DEFAULT_CHAIN_IDS.get(name, 0)
    return EvmChain(name=name, chain_id=chain_id, rpc=rpc, wss_urls=cfg.wss)


_DEFAULT_CHAIN_IDS = {"ethereum": 1, "base": 8453, "arbitrum": 42161, "bsc": 56}


def make_log_stream(chain: EvmChain, *, addresses=None, topics=None) -> EvmLogStream:
    if not chain.wss_urls:
        raise RuntimeError(f"no wss endpoints configured for chain={chain.name}")
    return EvmLogStream(chain.wss_urls, chain=chain.name, addresses=addresses, topics=topics)
