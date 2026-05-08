"""Чтение ERC20 metadata пакетами через multicall."""

from __future__ import annotations

from dataclasses import dataclass

from arb_intel.chains.evm.multicall import Call, encode_call, multicall
from arb_intel.chains.evm.rpc import JsonRpcPool


@dataclass(slots=True)
class TokenMeta:
    address: str
    symbol: str | None
    name: str | None
    decimals: int


def _decode_str(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.rstrip(b"\x00").decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(value, str):
        return value
    return str(value)


async def fetch_metadata(rpc: JsonRpcPool, addresses: list[str]) -> dict[str, TokenMeta]:
    if not addresses:
        return {}
    calls: list[Call] = []
    for a in addresses:
        calls.append(Call(a, encode_call("decimals()", [], []), ["uint8"], "decimals"))
        calls.append(Call(a, encode_call("symbol()", [], []), ["string"], "symbol"))
        calls.append(Call(a, encode_call("name()", [], []), ["string"], "name"))
    res = await multicall(rpc, calls)
    out: dict[str, TokenMeta] = {}
    for i, addr in enumerate(addresses):
        d, s, n = res[i * 3], res[i * 3 + 1], res[i * 3 + 2]
        try:
            decimals = int(d) if d is not None else 18
        except (TypeError, ValueError):
            decimals = 18
        out[addr.lower()] = TokenMeta(
            address=addr.lower(),
            symbol=_decode_str(s),
            name=_decode_str(n),
            decimals=decimals,
        )
    return out
