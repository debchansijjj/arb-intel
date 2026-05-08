"""Liquidity-state tracker.

Главная идея системы: реагируем на **изменение состояния пула**, а не на
агрегированную котировку. На каждом обновлении считаем `implied_price`
из state и публикуем в bus delta-event для scanner-а.

Поддерживаемые kind-ы:
  v2 / aerodrome  — reserve0, reserve1
  v3              — sqrtPriceX96, tick, liquidity
  whirlpool       — sqrtPriceX64, tick, liquidity
  dlmm            — active_id, bin_step
  raydium / pumpswap — vault balances (reserve0, reserve1) фактические
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from arb_intel.bus.streams import Streams, publish
from arb_intel.chains.evm.dexes.v2 import V2State
from arb_intel.chains.evm.dexes.v3 import V3State, price_from_sqrt
from arb_intel.tracking.pool_state import HotPoolState, read, write
from arb_intel.utils.metrics import events_seen
from arb_intel.utils.timeutil import now_ts


@dataclass(slots=True)
class StateDelta:
    chain: str
    pool: str
    prev_implied: float | None
    new_implied: float
    abs_bps: float
    block: int | None
    ts: float


async def update_v2(
    chain: str, pool: str, dex: str, fee_bps: int, token0: str, token1: str,
    decimals0: int, decimals1: int, state: V2State, *, source: str = "ws",
) -> StateDelta | None:
    if state.reserve0 <= 0 or state.reserve1 <= 0:
        return None
    # implied price = (reserve1 / 10^d1) / (reserve0 / 10^d0)
    implied = (state.reserve1 / (10**decimals1)) / (state.reserve0 / (10**decimals0))
    prev = await read(chain, pool)
    new = HotPoolState(
        chain=chain, pool=pool, dex=dex, kind="v2", fee_bps=fee_bps,
        token0=token0, token1=token1, decimals0=decimals0, decimals1=decimals1,
        implied_price=implied,
        reserve0=str(state.reserve0), reserve1=str(state.reserve1),
        block=state.block_number,
        ts=now_ts(),
        source=source,
    )
    await write(new)
    events_seen.labels(chain=chain, kind="v2_state").inc()
    delta = _delta(chain, pool, prev, implied, state.block_number)
    if delta:
        await publish(Streams.POOL_STATE, _delta_payload(new, delta))
    return delta


async def update_v3(
    chain: str, pool: str, dex: str, fee_bps: int, token0: str, token1: str,
    decimals0: int, decimals1: int, state: V3State, *, source: str = "ws",
) -> StateDelta | None:
    if state.sqrt_price_x96 == 0:
        return None
    implied = price_from_sqrt(state.sqrt_price_x96, decimals0, decimals1)
    prev = await read(chain, pool)
    new = HotPoolState(
        chain=chain, pool=pool, dex=dex, kind="v3", fee_bps=fee_bps,
        token0=token0, token1=token1, decimals0=decimals0, decimals1=decimals1,
        implied_price=implied,
        sqrt_price_x96=str(state.sqrt_price_x96), tick=state.tick,
        liquidity=str(state.liquidity), block=state.block_number,
        ts=now_ts(),
        source=source,
    )
    await write(new)
    events_seen.labels(chain=chain, kind="v3_state").inc()
    delta = _delta(chain, pool, prev, implied, state.block_number)
    if delta:
        await publish(Streams.POOL_STATE, _delta_payload(new, delta))
    return delta


async def update_solana_amm(
    chain: str, pool: str, dex: str, fee_bps: int, token0: str, token1: str,
    decimals0: int, decimals1: int, vault0: int, vault1: int, *, slot: int | None = None,
    source: str = "grpc",
) -> StateDelta | None:
    if vault0 <= 0 or vault1 <= 0:
        return None
    implied = (vault1 / (10**decimals1)) / (vault0 / (10**decimals0))
    prev = await read(chain, pool)
    new = HotPoolState(
        chain=chain, pool=pool, dex=dex, kind="raydium", fee_bps=fee_bps,
        token0=token0, token1=token1, decimals0=decimals0, decimals1=decimals1,
        implied_price=implied,
        reserve0=str(vault0), reserve1=str(vault1),
        slot=slot, ts=now_ts(), source=source,
    )
    await write(new)
    events_seen.labels(chain=chain, kind="sol_amm_state").inc()
    delta = _delta(chain, pool, prev, implied, slot)
    if delta:
        await publish(Streams.POOL_STATE, _delta_payload(new, delta))
    return delta


async def update_dlmm(
    chain: str, pool: str, dex: str, fee_bps: int, token0: str, token1: str,
    decimals0: int, decimals1: int, active_id: int, bin_step: int, *, slot: int | None = None,
    source: str = "grpc",
) -> StateDelta | None:
    base = 1.0 + bin_step / 10_000
    raw = base**active_id
    implied = raw * (10**decimals0) / (10**decimals1)
    prev = await read(chain, pool)
    new = HotPoolState(
        chain=chain, pool=pool, dex=dex, kind="dlmm", fee_bps=fee_bps,
        token0=token0, token1=token1, decimals0=decimals0, decimals1=decimals1,
        implied_price=implied,
        active_id=active_id, bin_step=bin_step,
        slot=slot, ts=now_ts(), source=source,
    )
    await write(new)
    events_seen.labels(chain=chain, kind="dlmm_state").inc()
    delta = _delta(chain, pool, prev, implied, slot)
    if delta:
        await publish(Streams.POOL_STATE, _delta_payload(new, delta))
    return delta


def _delta(chain: str, pool: str, prev: HotPoolState | None, new_impl: float, block: int | None) -> StateDelta:
    if prev is None or prev.implied_price <= 0:
        return StateDelta(chain=chain, pool=pool, prev_implied=None, new_implied=new_impl, abs_bps=0.0, block=block, ts=now_ts())
    diff = (new_impl - prev.implied_price) / prev.implied_price
    return StateDelta(
        chain=chain, pool=pool,
        prev_implied=prev.implied_price, new_implied=new_impl,
        abs_bps=abs(diff) * 10_000,
        block=block, ts=now_ts(),
    )


def _delta_payload(state: HotPoolState, delta: StateDelta) -> dict:
    return {
        "chain": state.chain,
        "pool": state.pool,
        "dex": state.dex,
        "kind": state.kind,
        "implied_price": state.implied_price,
        "prev_implied": delta.prev_implied,
        "abs_bps": delta.abs_bps,
        "ts": state.ts,
        "block": state.block,
        "slot": state.slot,
    }


# ---------------- batch refresher ----------------
async def periodic_refresher(loop_factory) -> None:
    """Запускает refresh-задачу с заданным интервалом, но без жёсткой
    привязки к конкретной chain — конкретику передаёт ``loop_factory``.
    """
    while True:
        with contextlib.suppress(Exception):
            await loop_factory()
        await asyncio.sleep(2.0)
