"""HTTPS RPC pool с health-check и rotation.

Не используем web3.py для request/response сами — слишком толсто и шумно
во внутренних метриках. Делаем прямой aiohttp/httpx JSON-RPC клиент.
web3.py всё равно используется для ABI-decoding/encoding.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass
from typing import Any

import httpx
import orjson

from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class _Endpoint:
    url: str
    healthy: bool = True
    last_failed_at: float = 0.0
    fail_streak: int = 0
    latency_ms_ewma: float = 0.0
    in_flight: int = 0


class JsonRpcPool:
    """Round-robin pool с deprioritisation плохих эндпоинтов."""

    def __init__(self, urls: list[str], *, name: str = "evm", timeout_s: float = 8.0) -> None:
        if not urls:
            raise ValueError("at least one rpc url required")
        self.name = name
        self._endpoints = [_Endpoint(url=u) for u in urls]
        self._cycle = itertools.cycle(self._endpoints)
        self._client = httpx.AsyncClient(timeout=timeout_s, http2=True)
        self._id = 0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _next_endpoint(self) -> _Endpoint:
        # Простая стратегия: первый "healthy" по кругу. Если все плохие —
        # возьмём наименее загруженный.
        n = len(self._endpoints)
        for _ in range(n):
            ep = next(self._cycle)
            if ep.healthy:
                return ep
        # все unhealthy — выбираем по min in_flight, ставим healthy=true (auto-recovery попытка)
        ep = min(self._endpoints, key=lambda e: e.in_flight)
        ep.healthy = True
        return ep

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        async with self._lock:
            self._id += 1
            req_id = self._id

        body = orjson.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or []})
        last_exc: Exception | None = None
        for _ in range(min(3, len(self._endpoints))):
            ep = self._next_endpoint()
            ep.in_flight += 1
            t0 = time.perf_counter()
            try:
                r = await self._client.post(
                    ep.url,
                    content=body,
                    headers={"content-type": "application/json"},
                )
                if r.status_code >= 500 or r.status_code == 429:
                    ep.fail_streak += 1
                    ep.last_failed_at = time.time()
                    if ep.fail_streak >= 3:
                        ep.healthy = False
                    raise httpx.HTTPStatusError("rpc upstream", request=r.request, response=r)
                data = orjson.loads(r.content)
                if data.get("error"):
                    raise RuntimeError(f"rpc error {data['error']}")
                latency = (time.perf_counter() - t0) * 1000
                ep.latency_ms_ewma = ep.latency_ms_ewma * 0.7 + latency * 0.3 if ep.latency_ms_ewma else latency
                ep.fail_streak = 0
                ep.healthy = True
                return data.get("result")
            except Exception as e:
                last_exc = e
                ep.fail_streak += 1
                ep.last_failed_at = time.time()
                if ep.fail_streak >= 3:
                    ep.healthy = False
                log.warning("rpc.fail", endpoint=ep.url, method=method, err=str(e))
            finally:
                ep.in_flight -= 1
        assert last_exc is not None
        raise last_exc

    async def batch(self, requests: list[tuple[str, list[Any] | None]]) -> list[Any]:
        if not requests:
            return []
        async with self._lock:
            base_id = self._id
            self._id += len(requests)
        body = orjson.dumps(
            [
                {"jsonrpc": "2.0", "id": base_id + i + 1, "method": m, "params": p or []}
                for i, (m, p) in enumerate(requests)
            ]
        )
        ep = self._next_endpoint()
        ep.in_flight += 1
        try:
            r = await self._client.post(ep.url, content=body, headers={"content-type": "application/json"})
            r.raise_for_status()
            arr = orjson.loads(r.content)
            arr.sort(key=lambda x: x["id"])
            results: list[Any] = []
            for item in arr:
                if item.get("error"):
                    results.append(RuntimeError(item["error"]))
                else:
                    results.append(item.get("result"))
            return results
        finally:
            ep.in_flight -= 1
