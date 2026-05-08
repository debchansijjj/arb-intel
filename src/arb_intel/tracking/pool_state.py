"""Унифицированный pool-state в Redis.

В отличие от Postgres ``pool_states``, Redis-snapshot — это **горячая
правда** для scanner-loop. Пишут трекеры, читает arbitrage engine.

Ключ: arb_intel:pool:{chain}:{pool_addr}
Значение (json):
{
  "kind": "v2|v3|whirlpool|raydium|dlmm|pumpswap",
  "chain": "...",
  "pool": "...",
  "dex": "...",
  "fee_bps": 30,
  "token0": "...", "token1": "...",
  "decimals0": 18, "decimals1": 6,
  "reserve0": "12345...", "reserve1": "9876...",   # v2-like (str BigInt)
  "sqrt_price_x96": "1234...",                     # v3
  "tick": 12345,
  "liquidity": "...",
  "active_id": -123,                               # dlmm
  "bin_step": 25,                                  # dlmm
  "implied_price": 0.0123,                         # token1/token0 (human)
  "last_swap_at": 1700000000.0,
  "tvl_usd": 12345.0,
  "block": 1234567,
  "ts": 1700000000.0,
  "source": "ws|grpc|multicall|bootstrap"
}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from arb_intel.cache.redis_client import read_pool_state, scan_pool_states, write_pool_state


@dataclass(slots=True)
class HotPoolState:
    chain: str
    pool: str
    dex: str
    kind: str
    fee_bps: int
    token0: str
    token1: str
    decimals0: int
    decimals1: int
    implied_price: float
    ts: float
    reserve0: str | None = None
    reserve1: str | None = None
    sqrt_price_x96: str | None = None
    tick: int | None = None
    liquidity: str | None = None
    active_id: int | None = None
    bin_step: int | None = None
    last_swap_at: float | None = None
    tvl_usd: float | None = None
    block: int | None = None
    slot: int | None = None
    source: str = "ws"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def write(state: HotPoolState, *, ttl_s: int = 24 * 3600) -> None:
    await write_pool_state(state.chain, state.pool, state.as_dict(), ttl_s=ttl_s)


async def read(chain: str, pool: str) -> HotPoolState | None:
    raw = await read_pool_state(chain, pool)
    if not raw:
        return None
    return HotPoolState(**{k: v for k, v in raw.items() if k in HotPoolState.__annotations__})


async def iter_all(chain: str | None = None):
    async for raw in scan_pool_states(chain):
        try:
            yield HotPoolState(**{k: v for k, v in raw.items() if k in HotPoolState.__annotations__})
        except TypeError:
            continue
