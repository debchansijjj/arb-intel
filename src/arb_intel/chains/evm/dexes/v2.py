"""Uniswap V2 / Sushi / Pancake / Aerodrome (constant-product flavour).

Aerodrome — частично stableswap. Здесь обрабатываем как v2 (volatile).
Stable-pair детектится по паре стейблов и считается с другим curve в
simulation engine (см. simulation/curves.py).
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import decode as abi_decode
from eth_utils import to_bytes

from arb_intel.chains.evm.abis import SYNC_TOPIC, V2_SWAP_TOPIC
from arb_intel.chains.evm.multicall import Call, encode_call
from arb_intel.chains.evm.rpc import JsonRpcPool
from arb_intel.chains.evm.ws import LogEvent


@dataclass(slots=True)
class V2State:
    pool: str
    reserve0: int
    reserve1: int
    block_number: int


@dataclass(slots=True)
class V2Swap:
    pool: str
    sender: str
    to_addr: str
    amount0_in: int
    amount1_in: int
    amount0_out: int
    amount1_out: int
    block_number: int
    tx_hash: str | None
    log_index: int | None


def parse_sync(event: LogEvent) -> V2State | None:
    if not event.topics or event.topics[0].lower() != SYNC_TOPIC:
        return None
    data = to_bytes(hexstr=event.data)
    r0, r1 = abi_decode(["uint112", "uint112"], data)
    return V2State(
        pool=event.address,
        reserve0=int(r0),
        reserve1=int(r1),
        block_number=event.block_number,
    )


def parse_swap(event: LogEvent) -> V2Swap | None:
    if not event.topics or event.topics[0].lower() != V2_SWAP_TOPIC:
        return None
    data = to_bytes(hexstr=event.data)
    a0in, a1in, a0out, a1out = abi_decode(["uint256", "uint256", "uint256", "uint256"], data)
    sender = "0x" + event.topics[1][-40:]
    to_addr = "0x" + event.topics[2][-40:]
    return V2Swap(
        pool=event.address,
        sender=sender,
        to_addr=to_addr,
        amount0_in=int(a0in),
        amount1_in=int(a1in),
        amount0_out=int(a0out),
        amount1_out=int(a1out),
        block_number=event.block_number,
        tx_hash=event.transaction_hash,
        log_index=event.log_index,
    )


# ---------------- multicall helpers ----------------
def calls_get_reserves(pools: list[str]) -> list[Call]:
    return [
        Call(
            target=p,
            data=encode_call("getReserves()", [], []),
            decode_types=["uint112", "uint112", "uint32"],
            label="getReserves",
        )
        for p in pools
    ]


def calls_token_pair(pools: list[str]) -> list[Call]:
    out: list[Call] = []
    for p in pools:
        out.append(Call(target=p, data=encode_call("token0()", [], []), decode_types=["address"], label="t0"))
        out.append(Call(target=p, data=encode_call("token1()", [], []), decode_types=["address"], label="t1"))
    return out


async def fetch_reserves(rpc: JsonRpcPool, pools: list[str]) -> dict[str, V2State]:
    from arb_intel.chains.evm.multicall import multicall

    if not pools:
        return {}
    res = await multicall(rpc, calls_get_reserves(pools))
    out: dict[str, V2State] = {}
    for pool, raw in zip(pools, res, strict=True):
        if raw is None:
            continue
        r0, r1, _ts = raw if isinstance(raw, tuple) else (raw,)
        out[pool.lower()] = V2State(pool=pool.lower(), reserve0=int(r0), reserve1=int(r1), block_number=0)
    return out
