"""multicall3 batching через прямой JSON-RPC.

Используется для:
- refresh reserves у V2-пулов пакетами
- slot0/liquidity у V3-пулов пакетами
- decimals/symbol у токенов пакетами
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import keccak, to_bytes, to_checksum_address

from arb_intel.chains.evm.abis import MULTICALL3_ADDR
from arb_intel.chains.evm.rpc import JsonRpcPool


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def encode_call(signature: str, types: list[str], values: list[Any]) -> bytes:
    return selector(signature) + abi_encode(types, values)


@dataclass(slots=True)
class Call:
    target: str
    data: bytes
    decode_types: list[str]
    label: str = ""


def _encode_aggregate3(calls: list[Call]) -> bytes:
    sel = selector("aggregate3((address,bool,bytes)[])")
    encoded = abi_encode(
        ["(address,bool,bytes)[]"],
        [[(to_checksum_address(c.target), True, c.data) for c in calls]],
    )
    return sel + encoded


def _decode_aggregate3(returndata: bytes) -> list[tuple[bool, bytes]]:
    decoded = abi_decode(["(bool,bytes)[]"], returndata)[0]
    return [(bool(s), bytes(d)) for s, d in decoded]


async def multicall(rpc: JsonRpcPool, calls: list[Call], *, block: str | int = "latest") -> list[Any | None]:
    if not calls:
        return []
    payload = _encode_aggregate3(calls)
    block_param = hex(block) if isinstance(block, int) else block
    raw = await rpc.call(
        "eth_call",
        [{"to": MULTICALL3_ADDR, "data": "0x" + payload.hex()}, block_param],
    )
    rd = to_bytes(hexstr=raw)
    # aggregate3 возвращает (Result[]); ABI у нас выше -> ((bool,bytes)[])
    # eth_abi distinct-парсит outer tuple, поэтому используем тот же decoder.
    decoded = abi_decode(["(bool,bytes)[]"], rd)[0]
    out: list[Any | None] = []
    for (success, data), call in zip(decoded, calls, strict=True):
        if not success or not data:
            out.append(None)
            continue
        try:
            values = abi_decode(call.decode_types, bytes(data))
            out.append(values if len(values) != 1 else values[0])
        except Exception:
            out.append(None)
    return out
