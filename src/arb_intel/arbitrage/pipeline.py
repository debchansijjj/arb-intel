"""Pipeline: candidate → simulate → heuristics → score → publish ranked opp.

Это основной потребитель ``OPP_CANDIDATE``. На каждом кандидате:
  1) подтягиваем hot-state buy/sell пулов;
  2) симулируем на ``configurable sizes`` ($100/$500/$1000/...);
  3) выбираем лучший по net_profit_usd;
  4) гоняем anti-fake heuristics;
  5) считаем confidence-score;
  6) публикуем в ``OPP_RANKED`` если score >= порога.
"""

from __future__ import annotations

import time

from arb_intel.bus.streams import Streams, consume, publish
from arb_intel.config import get_settings
from arb_intel.heuristics.engine import HeuristicEngine
from arb_intel.logging import get_logger
from arb_intel.scoring.score import score_opportunity
from arb_intel.simulation.simulator import SimResult, simulate_sizes
from arb_intel.tracking.pool_state import read

log = get_logger(__name__)


class OpportunityPipeline:
    def __init__(self) -> None:
        s = get_settings()
        self._sizes = s.arb.sim_sizes_usd
        self._min_score = s.arb.min_confidence
        self._min_profit = s.arb.min_net_profit_usd
        self._heur = HeuristicEngine()

    async def process(self, payload: dict) -> dict | None:
        buy = await read(payload["chain_buy"], payload["buy_pool"])
        sell = await read(payload["chain_sell"], payload["sell_pool"])
        if buy is None or sell is None:
            return None

        sims: list[SimResult] = await simulate_sizes(buy, sell, self._sizes)
        if not sims:
            return None
        best = max(sims, key=lambda s: s.net_profit_usd)
        if not best.feasible or best.net_profit_usd < self._min_profit:
            return None

        # heuristics
        heur = await self._heur.evaluate(buy, sell)
        if heur.is_fake:
            return None

        score = score_opportunity(
            kind=payload["kind"],
            spread_bps=payload.get("spread_bps", 0.0),
            best=best,
            heuristics=heur,
            buy=buy,
            sell=sell,
        )
        if score.confidence < self._min_score:
            return None

        ranked = {
            "kind": payload["kind"],
            "chain_buy": buy.chain,
            "chain_sell": sell.chain,
            "buy_pool": buy.pool,
            "sell_pool": sell.pool,
            "buy_dex": buy.dex,
            "sell_dex": sell.dex,
            "base_token": buy.token0,
            "quote_token": buy.token1,
            "spread_bps": payload.get("spread_bps", 0.0),
            "best_size_usd": best.notional_usd,
            "net_profit_usd": best.net_profit_usd,
            "gross_profit_usd": best.gross_profit_usd,
            "gas_usd": best.gas_usd,
            "bridge_usd": best.bridge_usd,
            "bridge_eta_s": best.bridge_eta_s,
            "avg_slippage_bps": best.avg_slippage_bps,
            "confidence": score.confidence,
            "score_breakdown": score.breakdown,
            "fake_reasons": heur.reasons,
            "ts": time.time(),
            "buy_implied": buy.implied_price,
            "sell_implied": sell.implied_price,
        }
        await publish(Streams.OPP_RANKED, ranked)
        return ranked


async def run_pipeline_loop() -> None:
    pipe = OpportunityPipeline()
    async for msg in consume(Streams.OPP_CANDIDATE, group="opp-pipeline", consumer="op-1"):
        try:
            await pipe.process(msg.payload)
        except Exception:
            log.exception("pipeline.error", payload=msg.payload)
