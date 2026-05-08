"""Solana tracker: подписка на программы DEX-ов через WS programSubscribe.

Стратегия:
- Слушаем ``programSubscribe`` для каждого программного ID с фильтром по
  data_size, чтобы не получать чужие аккаунты (offsets могут отличаться,
  но data_size крайне эффективен для отсева).
- Парсим state через layouts; для AMM-style (Raydium/PumpSwap) дополнительно
  тянем балансы vault'ов через ``getMultipleAccounts``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import base58
from sqlalchemy import select

from arb_intel.chains.solana.client import SolanaChain, build_solana, make_program_stream
from arb_intel.chains.solana.layouts.meteora_dlmm import parse_lb_pair
from arb_intel.chains.solana.layouts.orca_whirlpool import parse_whirlpool, price_from_sqrt_x64
from arb_intel.chains.solana.layouts.pumpswap import parse_pump_pool
from arb_intel.chains.solana.layouts.raydium_amm import parse_amm_info
from arb_intel.chains.solana.layouts.spl_token import parse_token_account
from arb_intel.chains.solana.program_ids import (
    METEORA_DLMM,
    ORCA_WHIRLPOOL,
    PUMP_SWAP,
    RAYDIUM_AMM_V4,
)
from arb_intel.config import get_settings
from arb_intel.db.models import Chain, Pool, Token
from arb_intel.db.session import session_scope
from arb_intel.logging import get_logger
from arb_intel.tracking.liquidity import update_dlmm, update_solana_amm
from arb_intel.utils.metrics import events_seen
from arb_intel.utils.timeutil import now_ts

log = get_logger(__name__)


@dataclass(slots=True)
class _PoolMeta:
    dex: str
    kind: str
    fee_bps: int
    token0: str          # base58
    token1: str
    decimals0: int
    decimals1: int


def _b58(b: bytes) -> str:
    return base58.b58encode(b).decode()


def _b58_decode(s: str) -> bytes:
    return base58.b58decode(s)


async def _resolve_meta(pool_pubkey: str) -> _PoolMeta | None:
    async with session_scope() as sess:
        chain_row = (await sess.execute(select(Chain).where(Chain.name == "solana"))).scalar_one_or_none()
        if chain_row is None:
            return None
        pool = (
            await sess.execute(
                select(Pool).where(Pool.chain_id == chain_row.id, Pool.address == pool_pubkey)
            )
        ).scalar_one_or_none()
        if pool is None:
            return None
        t0 = (await sess.execute(select(Token).where(Token.id == pool.token0_id))).scalar_one_or_none()
        t1 = (await sess.execute(select(Token).where(Token.id == pool.token1_id))).scalar_one_or_none()
        if t0 is None or t1 is None:
            return None
        return _PoolMeta(
            dex=pool.dex, kind=pool.kind, fee_bps=pool.fee_bps,
            token0=t0.address, token1=t1.address,
            decimals0=t0.decimals or 9, decimals1=t1.decimals or 9,
        )


async def _resolve_or_register_meta(pool_pubkey: str, *, dex: str, kind: str, fee_bps: int,
                                    base_mint: bytes, quote_mint: bytes,
                                    base_dec: int = 9, quote_dec: int = 9) -> _PoolMeta:
    """Если пул новый и не в БД — создаём минимальную запись."""
    from arb_intel.db.repositories import upsert_chain, upsert_pool, upsert_token

    async with session_scope() as sess:
        chain = await upsert_chain(sess, name="solana", family="solana")
        t0 = await upsert_token(sess, chain_id=chain.id, address=_b58(base_mint), symbol=None, name=None,
                                decimals=base_dec)
        t1 = await upsert_token(sess, chain_id=chain.id, address=_b58(quote_mint), symbol=None, name=None,
                                decimals=quote_dec)
        await upsert_pool(sess, chain_id=chain.id, address=pool_pubkey, dex=dex, kind=kind,
                          token0_id=t0.id, token1_id=t1.id, fee_bps=fee_bps)
    return _PoolMeta(dex=dex, kind=kind, fee_bps=fee_bps,
                     token0=_b58(base_mint), token1=_b58(quote_mint),
                     decimals0=base_dec, decimals1=quote_dec)


# ---------------- handlers per DEX ----------------
async def _handle_raydium(chain: SolanaChain, pool_pubkey: str, data: bytes) -> None:
    info = parse_amm_info(data)
    if info is None:
        return
    meta = await _resolve_or_register_meta(
        pool_pubkey, dex="raydium", kind="raydium", fee_bps=25,
        base_mint=info.base_mint, quote_mint=info.quote_mint,
        base_dec=int(info.base_decimal), quote_dec=int(info.quote_decimal),
    )
    # читаем балансы vault-аккаунтов
    accounts = await chain.rpc.get_multiple_accounts([_b58(info.base_vault), _b58(info.quote_vault)])
    if accounts[0] is None or accounts[1] is None:
        return
    a = parse_token_account(accounts[0].data)
    b = parse_token_account(accounts[1].data)
    if a is None or b is None:
        return
    await update_solana_amm(
        "solana", pool_pubkey, meta.dex, meta.fee_bps, meta.token0, meta.token1,
        meta.decimals0, meta.decimals1, a.amount, b.amount,
    )


async def _handle_pumpswap(chain: SolanaChain, pool_pubkey: str, data: bytes) -> None:
    info = parse_pump_pool(data)
    if info is None:
        return
    meta = await _resolve_or_register_meta(
        pool_pubkey, dex="pumpswap", kind="pumpswap", fee_bps=30,
        base_mint=info.base_mint, quote_mint=info.quote_mint,
        base_dec=6, quote_dec=9,  # pump tokens: 6 dec обычно, SOL — 9
    )
    accounts = await chain.rpc.get_multiple_accounts([_b58(info.base_vault), _b58(info.quote_vault)])
    if accounts[0] is None or accounts[1] is None:
        return
    a = parse_token_account(accounts[0].data)
    b = parse_token_account(accounts[1].data)
    if a is None or b is None:
        return
    await update_solana_amm(
        "solana", pool_pubkey, meta.dex, meta.fee_bps, meta.token0, meta.token1,
        meta.decimals0, meta.decimals1, a.amount, b.amount,
    )


async def _handle_whirlpool(_chain: SolanaChain, pool_pubkey: str, data: bytes) -> None:
    state = parse_whirlpool(data)
    if state is None:
        return
    meta = await _resolve_or_register_meta(
        pool_pubkey, dex="whirlpool", kind="whirlpool", fee_bps=state.fee_rate_bps,
        base_mint=state.token_mint_a, quote_mint=state.token_mint_b,
    )
    # переиспользуем v3-апдейтер: implied price считается от sqrt_price^2
    # У Whirlpool это X64. Нам нужен generic update — реюзаем сам
    # tracker, но передаём sqrt^2 как X96-совместимый: проще — посчитать
    # implied тут и записать через AMM-style.
    implied = price_from_sqrt_x64(state.sqrt_price_x64, meta.decimals0, meta.decimals1)
    from arb_intel.tracking.pool_state import HotPoolState, write
    hot = HotPoolState(
        chain="solana", pool=pool_pubkey, dex=meta.dex, kind="whirlpool",
        fee_bps=meta.fee_bps, token0=meta.token0, token1=meta.token1,
        decimals0=meta.decimals0, decimals1=meta.decimals1,
        implied_price=implied,
        sqrt_price_x96=str(state.sqrt_price_x64),  # сохраняем как X64
        tick=state.tick, liquidity=str(state.liquidity), ts=now_ts(), source="ws",
    )
    await write(hot)
    events_seen.labels(chain="solana", kind="whirlpool_state").inc()


async def _handle_dlmm(_chain: SolanaChain, pool_pubkey: str, data: bytes) -> None:
    state = parse_lb_pair(data)
    if state is None:
        return
    meta = await _resolve_or_register_meta(
        pool_pubkey, dex="meteora", kind="dlmm", fee_bps=30,
        base_mint=state.token_x_mint, quote_mint=state.token_y_mint,
    )
    await update_dlmm(
        "solana", pool_pubkey, meta.dex, meta.fee_bps, meta.token0, meta.token1,
        meta.decimals0, meta.decimals1, state.active_id, state.bin_step,
    )


_HANDLERS: dict[str, tuple[int, callable]] = {
    RAYDIUM_AMM_V4: (752, _handle_raydium),
    PUMP_SWAP: (224, _handle_pumpswap),
    ORCA_WHIRLPOOL: (653, _handle_whirlpool),
    METEORA_DLMM: (904, _handle_dlmm),
}


async def _watch_program(chain: SolanaChain, program_id: str) -> None:
    data_size, handler = _HANDLERS.get(program_id, (None, None))
    if handler is None:
        return
    log.info("sol_tracker.watch", program=program_id, data_size=data_size)
    stream = make_program_stream(chain, program_id, data_size=data_size)
    async for upd in stream:
        try:
            import base64
            data = base64.b64decode(upd.data_b64)
            await handler(chain, upd.pubkey, data)
        except Exception:
            log.exception("sol_tracker.handle_error", program=program_id, pubkey=upd.pubkey)


async def run_solana_tracker() -> None:
    s = get_settings()
    if "solana" not in s.chains.enabled:
        return
    chain = build_solana()
    try:
        tasks = [
            asyncio.create_task(_watch_program(chain, pid), name=f"sol_tail:{pid[:6]}")
            for pid in _HANDLERS
        ]
        await asyncio.gather(*tasks)
    finally:
        await chain.aclose()
