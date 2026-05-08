"""Solana JSON-RPC клиент.

Минималистичный async wrapper. Не используем solana.py клиент целиком
(слишком тяжёлый и shed compat-варнингов), но используем solders для
public-key/serialize.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx
import orjson

from arb_intel.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class AccountInfo:
    pubkey: str
    owner: str
    lamports: int
    data: bytes
    executable: bool
    rent_epoch: int


class SolanaRpc:
    def __init__(self, url: str, *, timeout_s: float = 8.0) -> None:
        self._url = url
        self._client = httpx.AsyncClient(timeout=timeout_s, http2=True)
        self._id = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        body = orjson.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        r = await self._client.post(self._url, content=body, headers={"content-type": "application/json"})
        r.raise_for_status()
        data = orjson.loads(r.content)
        if data.get("error"):
            raise RuntimeError(f"solana rpc error {data['error']}")
        return data.get("result")

    async def get_account_info(self, pubkey: str, *, commitment: str = "confirmed") -> AccountInfo | None:
        res = await self.call(
            "getAccountInfo",
            [pubkey, {"encoding": "base64", "commitment": commitment}],
        )
        value = (res or {}).get("value")
        if not value:
            return None
        data_b64, _enc = value["data"]
        return AccountInfo(
            pubkey=pubkey,
            owner=value["owner"],
            lamports=int(value["lamports"]),
            data=base64.b64decode(data_b64),
            executable=bool(value["executable"]),
            rent_epoch=int(value.get("rentEpoch", 0)),
        )

    async def get_multiple_accounts(
        self, pubkeys: list[str], *, commitment: str = "confirmed"
    ) -> list[AccountInfo | None]:
        if not pubkeys:
            return []
        out: list[AccountInfo | None] = []
        # Solana RPC limit ~100 per call
        for i in range(0, len(pubkeys), 100):
            chunk = pubkeys[i : i + 100]
            res = await self.call(
                "getMultipleAccounts",
                [chunk, {"encoding": "base64", "commitment": commitment}],
            )
            arr = (res or {}).get("value", [])
            for pubkey, item in zip(chunk, arr, strict=True):
                if item is None:
                    out.append(None)
                    continue
                data_b64, _enc = item["data"]
                out.append(
                    AccountInfo(
                        pubkey=pubkey,
                        owner=item["owner"],
                        lamports=int(item["lamports"]),
                        data=base64.b64decode(data_b64),
                        executable=bool(item["executable"]),
                        rent_epoch=int(item.get("rentEpoch", 0)),
                    )
                )
        return out

    async def get_program_accounts(
        self,
        program_id: str,
        *,
        filters: list[dict[str, Any]] | None = None,
        data_size: int | None = None,
        commitment: str = "confirmed",
    ) -> list[AccountInfo]:
        f = list(filters or [])
        if data_size is not None:
            f.append({"dataSize": data_size})
        res = await self.call(
            "getProgramAccounts",
            [program_id, {"encoding": "base64", "filters": f, "commitment": commitment}],
        )
        out: list[AccountInfo] = []
        for item in res or []:
            data_b64, _enc = item["account"]["data"]
            out.append(
                AccountInfo(
                    pubkey=item["pubkey"],
                    owner=item["account"]["owner"],
                    lamports=int(item["account"]["lamports"]),
                    data=base64.b64decode(data_b64),
                    executable=bool(item["account"]["executable"]),
                    rent_epoch=int(item["account"].get("rentEpoch", 0)),
                )
            )
        return out
