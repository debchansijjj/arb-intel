"""Uniswap V3 / Pancake V3 — concentrated liquidity.

Парсим Swap-event (новый sqrtPriceX96, liquidity, tick) и батчево читаем
slot0/liquidity через multicall для refresh.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import decode as abi_decode
from eth_utils import to_bytes

from arb_intel.chains.evm.abis import POOL_CREATED_TOPIC, V3_SWAP_TOPIC
from arb_intel.chains.evm.multicall import Call, encode_call
from arb_intel.chains.evm.rpc import JsonRpcPool
from arb_intel.chains.evm.ws import LogEvent


@dataclass(slots=True)
class V3State:
    pool: str
    sqrt_price_x96: int
    tick: int
    liquidity: int
    block_number: int


@dataclass(slots=True)
class V3Swap:
    pool: str
    sender: str
    recipient: str
    amount0: int   # signed
    amount1: int   # signed
    sqrt_price_x96: int
    liquidity: int
    tick: int
    block_number: int
    tx_hash: str | None
    log_index: int | None


def parse_pool_created(event: LogEvent) -> dict | None:
    if not event.topics or event.topics[0].lower() != POOL_CREATED_TOPIC:
        return None
    token0 = "0x" + event.topics[1][-40:]
    token1 = "0x" + event.topics[2][-40:]
    fee = int(event.topics[3], 16)
    data = to_bytes(hexstr=event.data)
    tick_spacing, pool = abi_decode(["int24", "address"], data)
    return {
        "token0": token0.lower(),
        "token1": token1.lower(),
        "fee": int(fee),
        "tick_spacing": int(tick_spacing),
        "pool": pool.lower(),
    }


def parse_swap(event: LogEvent) -> V3Swap | None:
    if not event.topics or event.topics[0].lower() != V3_SWAP_TOPIC:
        return None
    data = to_bytes(hexstr=event.data)
    amount0, amount1, sqrt_price_x96, liquidity, tick = abi_decode(
        ["int256", "int256", "uint160", "uint128", "int24"], data
    )
    sender = "0x" + event.topics[1][-40:]
    recipient = "0x" + event.topics[2][-40:]
    return V3Swap(
        pool=event.address,
        sender=sender,
        recipient=recipient,
        amount0=int(amount0),
        amount1=int(amount1),
        sqrt_price_x96=int(sqrt_price_x96),
        liquidity=int(liquidity),
        tick=int(tick),
        block_number=event.block_number,
        tx_hash=event.transaction_hash,
        log_index=event.log_index,
    )


# ---------------- multicall helpers ----------------
def calls_slot0(pools: list[str]) -> list[Call]:
    return [
        Call(
            target=p,
            data=encode_call("slot0()", [], []),
            decode_types=["uint160", "int24", "uint16", "uint16", "uint16", "uint8", "bool"],
            label="slot0",
        )
        for p in pools
    ]


def calls_liquidity(pools: list[str]) -> list[Call]:
    return [
        Call(target=p, data=encode_call("liquidity()", [], []), decode_types=["uint128"], label="L")
        for p in pools
    ]


async def fetch_state(rpc: JsonRpcPool, pools: list[str]) -> dict[str, V3State]:
    from arb_intel.chains.evm.multicall import multicall

    if not pools:
        return {}
    s0 = await multicall(rpc, calls_slot0(pools))
    liq = await multicall(rpc, calls_liquidity(pools))
    out: dict[str, V3State] = {}
    for pool, sl, lq in zip(pools, s0, liq, strict=True):
        if sl is None or lq is None:
            continue
        sqrt_price = int(sl[0]) if isinstance(sl, tuple) else int(sl)
        tick = int(sl[1]) if isinstance(sl, tuple) else 0
        out[pool.lower()] = V3State(
            pool=pool.lower(),
            sqrt_price_x96=sqrt_price,
            tick=tick,
            liquidity=int(lq),
            block_number=0,
        )
    return out


# ---------------- math ----------------
Q96 = 2**96


def price_from_sqrt(sqrt_price_x96: int, decimals0: int, decimals1: int) -> float:
    """Implied price token1/token0, normalised to human decimals."""
    if sqrt_price_x96 == 0:
        return 0.0
    p = (sqrt_price_x96 / Q96) ** 2
    return p * (10**decimals0) / (10**decimals1)
