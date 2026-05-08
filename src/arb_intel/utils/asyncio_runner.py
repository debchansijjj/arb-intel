"""Простой supervisor для конкурентных async-задач.

Перезапускает задачу с back-off при падении, аккуратно гасит при отмене.
Используется из всех воркеров.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Job:
    name: str
    factory: Callable[[], Awaitable[None]]
    restart: bool = True
    backoff_min_s: float = 1.0
    backoff_max_s: float = 30.0


class Supervisor:
    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        self._tasks = [asyncio.create_task(self._run_job(j), name=f"job:{j.name}") for j in self._jobs]
        try:
            await asyncio.wait(self._tasks, return_when=asyncio.FIRST_EXCEPTION)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_job(self, job: Job) -> None:
        backoff = job.backoff_min_s
        while not self._stopping.is_set():
            try:
                log.info("job.start", job=job.name)
                await job.factory()
                if not job.restart:
                    return
                log.info("job.exit_clean", job=job.name)
                backoff = job.backoff_min_s
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job.crash", job=job.name)
            sleep_s = backoff * (0.7 + random.random() * 0.6)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=sleep_s)
                return
            except TimeoutError:
                pass
            backoff = min(job.backoff_max_s, backoff * 1.7)
