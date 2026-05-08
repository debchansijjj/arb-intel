"""Главный execution simulator.

Принимает кандидата (buy_pool, sell_pool, base_token, quote_token,
notional_usd) и считает реальный net P&L:
  1) Конвертируем notional_usd → input_amount в quote_token (или base).
  2) На buy_pool: quote → base (получаем base_amount).
  3) На sell_pool: base → quote (получаем quote_back).
  4) PnL_quote = quote_back - quote_input. Конвертируем в USD.
  5) Вычитаем gas обоих транзакций + bridge.
  6) Учитываем pool_fee уже внутри curve-функций.
  7) Slippage = (notional_avg / notional_spot - 1) — внутри curve.
"""

from __future__ import annotations

from dataclasses import dataclass

from arb_intel.oracle.usd import usd_price
from arb_intel.simulation.bridges import bridge_cost
from arb_intel.simulation.curves import (
    V3PoolSnapshot,
    v2_amount_out,
    v2_price_impact_bps,
    v3_amount_out_in_range,
    whirlpool_amount_out_in_range,
)
from arb_intel.simulation.gas import estimate_gas_usd
from arb_intel.tracking.pool_state import HotPoolState


@dataclass(slots=True)
class SimResult:
    notional_usd: float
    base_amount: int            # сколько base получаем на buy
    quote_back: int             # сколько quote возвращаем на sell
    quote_in: int               # сколько quote вкладываем
    gross_profit_usd: float
    fees_usd: float
    gas_usd: float
    bridge_usd: float
    bridge_eta_s: int | None
    net_profit_usd: float
    avg_slippage_bps: float
    cross_chain: bool
    feasible: bool
    rejection_reason: str | None = None


def _swap_pool(
    pool: HotPoolState,
    amount_in: int,
    *,
    zero_for_one: bool,
) -> tuple[int, float]:
    """Возвращает (amount_out, price_impact_bps)."""
    if pool.kind in ("v2", "aerodrome", "raydium", "pumpswap"):
        r0 = int(pool.reserve0 or 0)
        r1 = int(pool.reserve1 or 0)
        if zero_for_one:
            out = v2_amount_out(amount_in, r0, r1, pool.fee_bps)
            impact = v2_price_impact_bps(amount_in, r0, r1, pool.fee_bps)
        else:
            out = v2_amount_out(amount_in, r1, r0, pool.fee_bps)
            impact = v2_price_impact_bps(amount_in, r1, r0, pool.fee_bps)
        return out, impact
    if pool.kind == "v3":
        snap = V3PoolSnapshot(
            sqrt_price_x96=int(pool.sqrt_price_x96 or 0),
            liquidity=int(pool.liquidity or 0),
            fee_bps=pool.fee_bps,
            decimals0=pool.decimals0,
            decimals1=pool.decimals1,
        )
        return v3_amount_out_in_range(amount_in, snap, zero_for_one=zero_for_one)
    if pool.kind == "whirlpool":
        out = whirlpool_amount_out_in_range(
            amount_in,
            int(pool.sqrt_price_x96 or 0),
            int(pool.liquidity or 0),
            pool.fee_bps,
            zero_for_one=zero_for_one,
        )
        return out, 0.0
    if pool.kind == "dlmm":
        # для DLMM в-range price считаем как (1+bin_step/10000)^active_id;
        # ликвидность одного bin не известна без чтения bin_array — даём
        # консервативную V2-аппроксимацию по implied_price.
        if pool.implied_price <= 0:
            return 0, 10_000.0
        if zero_for_one:
            out = int(amount_in * pool.implied_price * (1 - pool.fee_bps / 10_000))
        else:
            out = int(amount_in / pool.implied_price * (1 - pool.fee_bps / 10_000))
        return out, 30.0  # эвристика 30bps deg для среднего sized свопа
    return 0, 10_000.0


def _quote_unit_per_usd(pool: HotPoolState, quote_usd: float) -> float:
    """Сколько единиц quote-токена соответствует $1."""
    if quote_usd <= 0:
        return 0.0
    return (10**pool.decimals1) / quote_usd


async def simulate(
    buy_pool: HotPoolState,
    sell_pool: HotPoolState,
    notional_usd: float,
) -> SimResult:
    # Базовое предусловие: оба пула на одной паре (token0/token1 совпадают
    # с точностью до перестановки)
    cross_chain = buy_pool.chain != sell_pool.chain
    pair_buy = (buy_pool.token0, buy_pool.token1)
    pair_sell = (sell_pool.token0, sell_pool.token1)
    if set(pair_buy) != set(pair_sell):
        return SimResult(
            notional_usd=notional_usd, base_amount=0, quote_back=0, quote_in=0,
            gross_profit_usd=0.0, fees_usd=0.0, gas_usd=0.0, bridge_usd=0.0,
            bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=10_000.0,
            cross_chain=cross_chain, feasible=False,
            rejection_reason="pair_mismatch",
        )

    # Принимаем "quote" как token1 buy_pool (обычно стейбл/eth/wsol)
    quote_addr = buy_pool.token1
    base_addr = buy_pool.token0
    quote_usd = await usd_price(buy_pool.chain, quote_addr)
    if quote_usd is None or quote_usd.usd <= 0:
        return SimResult(
            notional_usd=notional_usd, base_amount=0, quote_back=0, quote_in=0,
            gross_profit_usd=0.0, fees_usd=0.0, gas_usd=0.0, bridge_usd=0.0,
            bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=10_000.0,
            cross_chain=cross_chain, feasible=False,
            rejection_reason="no_usd_price",
        )

    quote_in = int(notional_usd * (10**buy_pool.decimals1) / quote_usd.usd)
    if quote_in <= 0:
        return SimResult(
            notional_usd=notional_usd, base_amount=0, quote_back=0, quote_in=0,
            gross_profit_usd=0.0, fees_usd=0.0, gas_usd=0.0, bridge_usd=0.0,
            bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=10_000.0,
            cross_chain=cross_chain, feasible=False,
            rejection_reason="zero_input",
        )

    # buy_pool: quote(token1) -> base(token0) ⇒ direction = false (one_for_zero)
    base_out, buy_impact = _swap_pool(buy_pool, quote_in, zero_for_one=False)
    if base_out <= 0:
        return SimResult(
            notional_usd=notional_usd, base_amount=0, quote_back=0, quote_in=quote_in,
            gross_profit_usd=0.0, fees_usd=0.0, gas_usd=0.0, bridge_usd=0.0,
            bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=10_000.0,
            cross_chain=cross_chain, feasible=False, rejection_reason="buy_zero",
        )

    # На sell_pool token0/token1 могут быть в обратном порядке
    if sell_pool.token0 == base_addr and sell_pool.token1 == quote_addr:
        quote_back, sell_impact = _swap_pool(sell_pool, base_out, zero_for_one=True)
    else:
        quote_back, sell_impact = _swap_pool(sell_pool, base_out, zero_for_one=False)
    if quote_back <= 0:
        return SimResult(
            notional_usd=notional_usd, base_amount=base_out, quote_back=0, quote_in=quote_in,
            gross_profit_usd=0.0, fees_usd=0.0, gas_usd=0.0, bridge_usd=0.0,
            bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=10_000.0,
            cross_chain=cross_chain, feasible=False, rejection_reason="sell_zero",
        )

    # USD PnL
    gross_quote = quote_back - quote_in
    gross_profit_usd = (gross_quote / (10**buy_pool.decimals1)) * quote_usd.usd

    gas_buy = estimate_gas_usd(buy_pool.chain)
    gas_sell = estimate_gas_usd(sell_pool.chain)
    gas_usd = gas_buy + gas_sell
    bridge_usd = 0.0
    bridge_eta = None
    if cross_chain:
        bc = bridge_cost(buy_pool.chain, sell_pool.chain, notional_usd)
        if bc is None:
            return SimResult(
                notional_usd=notional_usd, base_amount=base_out, quote_back=quote_back, quote_in=quote_in,
                gross_profit_usd=gross_profit_usd, fees_usd=0.0, gas_usd=gas_usd, bridge_usd=0.0,
                bridge_eta_s=None, net_profit_usd=-1e9, avg_slippage_bps=(buy_impact + sell_impact) / 2,
                cross_chain=True, feasible=False, rejection_reason="no_bridge",
            )
        bridge_usd = bc.flat_usd
        bridge_eta = bc.eta_s

    net_profit_usd = gross_profit_usd - gas_usd - bridge_usd
    avg_slippage_bps = (buy_impact + sell_impact) / 2.0

    return SimResult(
        notional_usd=notional_usd,
        base_amount=base_out,
        quote_back=quote_back,
        quote_in=quote_in,
        gross_profit_usd=gross_profit_usd,
        fees_usd=0.0,  # уже встроены в curve-математику
        gas_usd=gas_usd,
        bridge_usd=bridge_usd,
        bridge_eta_s=bridge_eta,
        net_profit_usd=net_profit_usd,
        avg_slippage_bps=avg_slippage_bps,
        cross_chain=cross_chain,
        feasible=net_profit_usd > 0,
    )


async def simulate_sizes(
    buy_pool: HotPoolState,
    sell_pool: HotPoolState,
    sizes_usd: list[float],
) -> list[SimResult]:
    out: list[SimResult] = []
    for s in sizes_usd:
        out.append(await simulate(buy_pool, sell_pool, s))
    return out
