"""All-in-one entry: запускает FastAPI control plane + supervisor с воркерами.

Удобно для dev/одиночного контейнера. Для горизонтального масштабирования
используется ``arb-intel-worker`` с конкретным kind.
"""

from __future__ import annotations

import asyncio

import uvicorn

from arb_intel.api.app import app
from arb_intel.config import get_settings
from arb_intel.logging import configure_logging, get_logger
from arb_intel.utils.asyncio_runner import Job, Supervisor
from arb_intel.workers.entrypoint import _all_jobs

log = get_logger(__name__)


async def _run_api() -> None:
    s = get_settings()
    config = uvicorn.Config(
        app,
        host=s.api.host,
        port=s.api.port,
        log_level=s.log_level.lower(),
        loop="asyncio",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_all() -> None:
    configure_logging()
    sup = Supervisor(
        [
            Job(name="api", factory=_run_api),
            *_all_jobs(),
        ]
    )
    await sup.run()


def main() -> None:
    asyncio.run(_run_all())


if __name__ == "__main__":
    main()
