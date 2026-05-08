"""Solana WS subscription helper (programSubscribe / accountSubscribe / logsSubscribe).

Используется как fallback к Yellowstone gRPC — например, если у пользователя
нет Helius/Triton подписки, мы всё ещё можем получать обновления через
public WS (с ограничениями rate-limit публичного RPC).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass

import orjson
import websockets

from arb_intel.logging import get_logger
from arb_intel.utils.metrics import ws_reconnects

log = get_logger(__name__)


@dataclass(slots=True)
class AccountUpdate:
    pubkey: str
    owner: str
    data_b64: str
    slot: int


class SolanaProgramSubscription:
    """``programSubscribe`` — слушаем все аккаунты конкретного program-id с фильтром по data_size.

    Полезно для отлова новых пулов / state-updates без лишнего трафика.
    """

    def __init__(
        self,
        urls: list[str],
        program_id: str,
        *,
        data_size: int | None = None,
        commitment: str = "confirmed",
        ping_interval: float = 25.0,
    ) -> None:
        if not urls:
            raise ValueError("at least one wss url required")
        self._urls = list(urls)
        self._cycle = itertools.cycle(self._urls)
        self._program_id = program_id
        self._data_size = data_size
        self._commitment = commitment
        self._ping_interval = ping_interval
        self._stopping = asyncio.Event()

    async def stop(self) -> None:
        self._stopping.set()

    async def __aiter__(self) -> AsyncIterator[AccountUpdate]:
        backoff = 1.0
        while not self._stopping.is_set():
            url = next(self._cycle)
            try:
                async for update in self._run_once(url):
                    backoff = 1.0
                    yield update
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sol.ws.error", url=url, program=self._program_id)
                ws_reconnects.labels(chain="solana", endpoint=url).inc()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=backoff)
                return
            except TimeoutError:
                pass
            backoff = min(30.0, backoff * 1.7)

    async def _run_once(self, url: str) -> AsyncIterator[AccountUpdate]:
        async with websockets.connect(url, ping_interval=self._ping_interval) as ws:
            params = [
                self._program_id,
                {
                    "encoding": "base64",
                    "commitment": self._commitment,
                    **({"filters": [{"dataSize": self._data_size}]} if self._data_size else {}),
                },
            ]
            req = {"jsonrpc": "2.0", "id": 1, "method": "programSubscribe", "params": params}
            await ws.send(orjson.dumps(req).decode())
            sub_id: int | None = None
            try:
                async for raw in ws:
                    msg = orjson.loads(raw)
                    if msg.get("id") == 1:
                        if msg.get("error"):
                            raise RuntimeError(f"sol subscribe error: {msg['error']}")
                        sub_id = msg.get("result")
                        log.info("sol.ws.subscribed", program=self._program_id, sub=sub_id)
                        continue
                    if msg.get("method") != "programNotification":
                        continue
                    p = msg["params"]["result"]
                    val = p["value"]
                    yield AccountUpdate(
                        pubkey=val["pubkey"],
                        owner=val["account"]["owner"],
                        data_b64=val["account"]["data"][0],
                        slot=int(p["context"]["slot"]),
                    )
            finally:
                with contextlib.suppress(Exception):
                    if sub_id is not None:
                        await ws.send(
                            orjson.dumps(
                                {"jsonrpc": "2.0", "id": 99, "method": "programUnsubscribe", "params": [sub_id]}
                            ).decode()
                        )
