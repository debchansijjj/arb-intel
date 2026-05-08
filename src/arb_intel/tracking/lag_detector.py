"""Lag detector: ловит ситуации, когда один пул на токене **уже двинулся**,
а другой — ещё нет.

Алгоритм:
1. По каждому токену из tier 2/3 строим пары пулов на разных DEX/chain.
2. Если на одном пуле произошла большая state-delta (`StateDelta.abs_bps`)
   за последние ``lag_window_s`` секунд, а на другом за тот же интервал
   delta мала ИЛИ implied_price не догнал — считаем "лаг-окно".
3. Передаём в scanner с приоритетом.

Это работает поверх Redis hot-state и stream Streams.POOL_STATE.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from arb_intel.bus.streams import Streams, consume, publish
from arb_intel.config import get_settings
from arb_intel.logging import get_logger
from arb_intel.tracking.pool_state import HotPoolState, read

log = get_logger(__name__)


@dataclass(slots=True)
class _PoolSnap:
    implied: float
    ts: float
    abs_bps: float


class LagDetector:
    def __init__(self) -> None:
        s = get_settings()
        self._window = s.arb.lag_window_s
        self._min_move_bps = max(20, s.arb.min_spread_bps // 2)
        # token_key -> deque of recent snaps по разным пулам:
        self._snaps: dict[str, dict[str, deque[_PoolSnap]]] = defaultdict(lambda: defaultdict(deque))

    @staticmethod
    def _token_key(state: HotPoolState) -> str:
        # Привязываем по «base token» — приоритет самой сильной пары token0/token1
        # к стейблу: упрощённо берём оба, но для группировки используем set.
        return ":".join(sorted([f"{state.chain}:{state.token0}", f"{state.chain}:{state.token1}"]))

    def _trim(self, dq: deque[_PoolSnap], horizon_s: float) -> None:
        cutoff = time.time() - horizon_s
        while dq and dq[0].ts < cutoff:
            dq.popleft()

    async def ingest_event(self, payload: dict) -> dict | None:
        chain = payload["chain"]
        pool = payload["pool"]
        state = await read(chain, pool)
        if state is None:
            return None
        token_key = self._token_key(state)
        snap = _PoolSnap(implied=state.implied_price, ts=state.ts, abs_bps=payload.get("abs_bps", 0.0))
        dq = self._snaps[token_key][f"{chain}:{pool}"]
        dq.append(snap)
        self._trim(dq, self._window)

        # ищем второй пул для той же токен-группы, у которого implied
        # отстаёт за этот же интервал
        candidates = self._snaps[token_key]
        if len(candidates) < 2:
            return None

        # выбираем пул, который больше всего двинулся
        movers = [(k, v) for k, v in candidates.items() if v and v[-1].abs_bps >= self._min_move_bps]
        if not movers:
            return None
        mover_key, _mover_dq = max(movers, key=lambda kv: kv[1][-1].abs_bps)
        mover_state = await read(*mover_key.split(":", 1))
        if mover_state is None:
            return None

        for other_key, other_dq in candidates.items():
            if other_key == mover_key or not other_dq:
                continue
            other_state = await read(*other_key.split(":", 1))
            if other_state is None or other_state.implied_price <= 0:
                continue
            spread = abs(other_state.implied_price - mover_state.implied_price) / mover_state.implied_price
            spread_bps = spread * 10_000
            # «лаг»: спред появился, но второй пул двинулся мало
            other_recent_move = max((s.abs_bps for s in other_dq), default=0.0)
            if spread_bps >= self._min_move_bps and other_recent_move < self._min_move_bps * 0.5:
                lag_evt = {
                    "kind": "lagging",
                    "chain": chain,
                    "token0": state.token0,
                    "token1": state.token1,
                    "leader": {"chain": mover_state.chain, "pool": mover_state.pool, "dex": mover_state.dex,
                               "implied": mover_state.implied_price},
                    "lagger": {"chain": other_state.chain, "pool": other_state.pool, "dex": other_state.dex,
                               "implied": other_state.implied_price},
                    "spread_bps": spread_bps,
                    "ts": time.time(),
                }
                await publish(Streams.OPP_CANDIDATE, lag_evt)
                return lag_evt
        return None


async def run_lag_detector_loop() -> None:
    detector = LagDetector()
    async for msg in consume(Streams.POOL_STATE, group="lag-detector", consumer="lagd-1"):
        try:
            await detector.ingest_event(msg.payload)
        except Exception:
            log.exception("lag.error", payload=msg.payload)
