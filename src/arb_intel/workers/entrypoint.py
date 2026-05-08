"""Универсальная точка входа для запуска одного или нескольких воркеров.

Запуск:
    arb-intel-worker discovery
    arb-intel-worker tracker:base
    arb-intel-worker tracker:solana
    arb-intel-worker scanner
    arb-intel-worker alerts
    arb-intel-worker all          # all-in-one для разработки

Каждый «kind» — это набор Job-ов в supervisor.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from collections.abc import Awaitable, Callable

from arb_intel.arbitrage.pipeline import run_pipeline_loop
from arb_intel.arbitrage.scanner import (
    run_cross_chain_loop,
    run_fresh_pool_loop,
    run_state_delta_scanner,
)
from arb_intel.config import get_settings
from arb_intel.discovery.bootstrap import bootstrap_loop
from arb_intel.discovery.onchain import run_onchain_discovery
from arb_intel.logging import configure_logging, get_logger
from arb_intel.telegram.bot import run_alert_loop
from arb_intel.tracking.evm_tracker import run_evm_tracker
from arb_intel.tracking.lag_detector import run_lag_detector_loop
from arb_intel.tracking.solana_tracker import run_solana_tracker
from arb_intel.utils.asyncio_runner import Job, Supervisor

log = get_logger(__name__)


def _discovery_jobs() -> list[Job]:
    return [
        Job(name="discovery:bootstrap", factory=bootstrap_loop),
        Job(name="discovery:onchain", factory=run_onchain_discovery),
    ]


def _tracker_jobs(target: str | None = None) -> list[Job]:
    s = get_settings()
    jobs: list[Job] = []
    chains = [target] if target else list(s.chains.enabled)
    for chain in chains:
        if chain == "solana":
            jobs.append(Job(name="tracker:solana", factory=run_solana_tracker))
        else:
            jobs.append(
                Job(name=f"tracker:{chain}", factory=lambda c=chain: run_evm_tracker(c))
            )
    return jobs


def _scanner_jobs() -> list[Job]:
    return [
        Job(name="scanner:state", factory=run_state_delta_scanner),
        Job(name="scanner:lag", factory=run_lag_detector_loop),
        Job(name="scanner:cross_chain", factory=run_cross_chain_loop),
        Job(name="scanner:fresh", factory=run_fresh_pool_loop),
        Job(name="scanner:pipeline", factory=run_pipeline_loop),
    ]


def _alert_jobs() -> list[Job]:
    return [Job(name="alerts:telegram", factory=run_alert_loop)]


def _all_jobs() -> list[Job]:
    return [
        *_discovery_jobs(),
        *_tracker_jobs(),
        *_scanner_jobs(),
        *_alert_jobs(),
    ]


_DISPATCH: dict[str, Callable[[], list[Job]]] = {
    "discovery": _discovery_jobs,
    "tracker": _tracker_jobs,
    "scanner": _scanner_jobs,
    "alerts": _alert_jobs,
    "all": _all_jobs,
}


def _resolve(kind: str) -> list[Job]:
    if ":" in kind:
        head, tail = kind.split(":", 1)
        if head == "tracker":
            return _tracker_jobs(tail)
    fn = _DISPATCH.get(kind)
    if not fn:
        raise SystemExit(f"unknown worker kind: {kind} (allowed: {list(_DISPATCH)})")
    return fn()


async def _run(kind: str) -> None:
    configure_logging()
    jobs = _resolve(kind)
    sup = Supervisor(jobs)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _signal_handler() -> None:
        log.info("signal.shutdown")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # windows
            loop.add_signal_handler(sig, _signal_handler)

    runner: Awaitable[None] = sup.run()
    runner_task = asyncio.create_task(runner, name=f"sup:{kind}")
    stopper = asyncio.create_task(stop.wait(), name="sup:stop")
    done, _pending = await asyncio.wait({runner_task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    if stopper in done:
        await sup.shutdown()
        runner_task.cancel()


def main() -> None:
    if len(sys.argv) < 2:
        print(f"usage: arb-intel-worker [{'|'.join(_DISPATCH)}|tracker:<chain>]", file=sys.stderr)
        sys.exit(2)
    kind = sys.argv[1]
    asyncio.run(_run(kind))


if __name__ == "__main__":
    main()
