"""eth_subscribe('logs', ...) поверх websockets.

Работает напрямую (без web3 ws) — это даёт минимальный overhead и контроль
над reconnect/dedup. Любой EVM-WSS должен поддерживать стандартный
``eth_subscribe`` (Erigon/Geth/Reth/большинство managed RPC).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any

import orjson
import websockets

from arb_intel.logging import get_logger
from arb_intel.utils.metrics import ws_reconnects

log = get_logger(__name__)


@dataclass(slots=True)
class LogEvent:
    address: str
    topics: list[str]
    data: str
    block_number: int
    transaction_hash: str | None
    log_index: int | None


class EvmLogStream:
    """Async iterable over eth_subscribe('logs') filtered by address+topics."""

    def __init__(
        self,
        urls: list[str],
        *,
        chain: str,
        addresses: Iterable[str] | None = None,
        topics: Iterable[str | list[str]] | None = None,
        ping_interval: float = 20.0,
    ) -> None:
        if not urls:
            raise ValueError("at least one wss url required")
        self.chain = chain
        self._urls = list(urls)
        self._cycle = itertools.cycle(self._urls)
        self._addresses = [a.lower() for a in addresses] if addresses else None
        self._topics = list(topics) if topics else None
        self._ping_interval = ping_interval
        self._stopping = asyncio.Event()

    async def stop(self) -> None:
        self._stopping.set()

    async def __aiter__(self) -> AsyncIterator[LogEvent]:
        backoff = 1.0
        while not self._stopping.is_set():
            url = next(self._cycle)
            try:
                async for event in self._run_once(url):
                    backoff = 1.0
                    yield event
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ws.stream_error", chain=self.chain, url=url)
                ws_reconnects.labels(chain=self.chain, endpoint=url).inc()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=backoff)
                return
            except TimeoutError:
                pass
            backoff = min(30.0, backoff * 1.7)

    async def _run_once(self, url: str) -> AsyncIterator[LogEvent]:
        log.info("ws.connect", chain=self.chain, url=url)
        async with websockets.connect(url, ping_interval=self._ping_interval) as ws:
            sub_id = await self._subscribe(ws)
            log.info("ws.subscribed", chain=self.chain, sub=sub_id)
            try:
                async for raw in ws:
                    msg = orjson.loads(raw)
                    if msg.get("method") != "eth_subscription":
                        continue
                    p = msg["params"].get("result", {})
                    yield LogEvent(
                        address=p.get("address", "").lower(),
                        topics=p.get("topics", []),
                        data=p.get("data", "0x"),
                        block_number=int(p.get("blockNumber", "0x0"), 16),
                        transaction_hash=p.get("transactionHash"),
                        log_index=int(p["logIndex"], 16) if p.get("logIndex") else None,
                    )
            finally:
                with contextlib.suppress(Exception):
                    await ws.send(orjson.dumps({"id": 99, "method": "eth_unsubscribe", "params": [sub_id]}).decode())

    async def _subscribe(self, ws: websockets.WebSocketClientProtocol) -> str:
        params: dict[str, Any] = {}
        if self._addresses:
            params["address"] = self._addresses if len(self._addresses) > 1 else self._addresses[0]
        if self._topics:
            params["topics"] = self._topics
        req = {"id": 1, "jsonrpc": "2.0", "method": "eth_subscribe", "params": ["logs", params]}
        await ws.send(orjson.dumps(req).decode())
        # ack
        while True:
            msg = orjson.loads(await ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(f"subscribe error: {msg['error']}")
                return msg["result"]
