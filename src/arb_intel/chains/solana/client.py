"""Высокоуровневый Solana-клиент: rpc + ws/grpc geyser + helpers."""

from __future__ import annotations

from dataclasses import dataclass

from arb_intel.chains.solana.rpc import SolanaRpc
from arb_intel.chains.solana.ws import SolanaProgramSubscription
from arb_intel.chains.solana.yellowstone import YellowstoneClient, make_yellowstone_or_none
from arb_intel.config import get_settings


@dataclass(slots=True)
class SolanaChain:
    rpc: SolanaRpc
    wss_urls: list[str]
    yellowstone: YellowstoneClient | None
    commitment: str = "confirmed"

    async def aclose(self) -> None:
        await self.rpc.aclose()


def build_solana() -> SolanaChain:
    s = get_settings()
    return SolanaChain(
        rpc=SolanaRpc(s.solana.rpc_https),
        wss_urls=[s.solana.rpc_wss],
        yellowstone=make_yellowstone_or_none(),
        commitment=s.solana.commitment,
    )


def make_program_stream(chain: SolanaChain, program_id: str, *, data_size: int | None = None):
    return SolanaProgramSubscription(
        chain.wss_urls,
        program_id,
        data_size=data_size,
        commitment=chain.commitment,
    )
