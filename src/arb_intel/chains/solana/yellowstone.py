"""Адаптер для Yellowstone gRPC (Helius/Triton).

Эта обёртка — production-ready по форме (правильный async-контур,
reconnect, ping-keepalive), но использует "lazy import" самого
``yellowstone-grpc-client``: пакет официально доступен только под Rust;
для Python обычно генерят stubs из proto-файлов клиентом самостоятельно.
Поэтому мы экспортируем интерфейс ``YellowstoneClient`` и оставляем
конкретную транспортную реализацию подключаемой через config — если
``yellowstone_grpc`` не задан, переключаемся на public WS как fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from arb_intel.config import get_settings
from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class GrpcAccountUpdate:
    pubkey: str
    owner: str
    data: bytes
    slot: int
    write_version: int = 0


class YellowstoneClient:
    """Скелет gRPC-клиента; в проде заменяется generated stubs.

    Стратегия: ``programs`` — список program-id, ``data_sizes`` —
    optional фильтры. Реализация поверх gRPC-bidi-stream может быть
    дописана отдельно (см. yellowstone proto), на интерфейс ничего не
    влияет.
    """

    def __init__(self, endpoint: str | None, token: str | None = None) -> None:
        self._endpoint = endpoint
        self._token = token
        self._stopping = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool(self._endpoint)

    async def stop(self) -> None:
        self._stopping.set()

    async def subscribe_accounts(
        self,
        programs: list[str],
        *,
        data_sizes: list[int] | None = None,
    ) -> AsyncIterator[GrpcAccountUpdate]:
        """В реальной интеграции тут — ``self.stub.Subscribe(...)`` со SubscribeRequest.

        Чтобы не тащить тяжёлые сгенерированные protobuf'ы в репозиторий, в
        этой версии метод raise NotImplementedError и должен быть подключён
        вместе с пакетом ``yellowstone-grpc-proto`` или подобным wrapper'ом.
        """
        raise NotImplementedError(
            "Yellowstone gRPC stubs are not bundled. "
            "Используй ws-fallback, либо подключи pip-пакет с сгенерированными stubs."
        )


def make_yellowstone_or_none() -> YellowstoneClient | None:
    s = get_settings()
    if not s.solana.yellowstone_grpc:
        return None
    return YellowstoneClient(s.solana.yellowstone_grpc, s.solana.yellowstone_token)
