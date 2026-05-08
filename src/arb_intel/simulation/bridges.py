"""Cross-chain cost / latency model.

Очень упрощённая, но честная: для каждой пары chain->chain хранится
ожидаемое время моста (sec) и комиссия (USD + bps). На основе этого
arbitrage engine отбраковывает cross-chain возможности, у которых
EV < 0 после моста.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BridgeCost:
    eta_s: int
    flat_usd: float
    bps: int


# Дефолты на основе типичных стоимостей. В проде заменяем на live-quote
# из Across/Stargate/deBridge.
_BRIDGE: dict[tuple[str, str], BridgeCost] = {
    ("base", "arbitrum"): BridgeCost(60, 0.5, 5),
    ("arbitrum", "base"): BridgeCost(60, 0.5, 5),
    ("base", "ethereum"): BridgeCost(900, 5.0, 10),
    ("ethereum", "base"): BridgeCost(900, 5.0, 10),
    ("arbitrum", "ethereum"): BridgeCost(1200, 5.0, 10),
    ("ethereum", "arbitrum"): BridgeCost(60, 1.0, 7),
    ("bsc", "ethereum"): BridgeCost(900, 6.0, 15),
    ("ethereum", "bsc"): BridgeCost(900, 6.0, 15),
    ("solana", "ethereum"): BridgeCost(600, 8.0, 20),
    ("ethereum", "solana"): BridgeCost(600, 8.0, 20),
    ("solana", "base"): BridgeCost(600, 6.0, 15),
    ("base", "solana"): BridgeCost(600, 6.0, 15),
}


def bridge_cost(src: str, dst: str, notional_usd: float) -> BridgeCost | None:
    if src == dst:
        return None
    bc = _BRIDGE.get((src, dst))
    if bc is None:
        return None
    return BridgeCost(eta_s=bc.eta_s, flat_usd=bc.flat_usd + notional_usd * bc.bps / 10_000, bps=bc.bps)


def is_cross_chain_supported(src: str, dst: str) -> bool:
    return (src, dst) in _BRIDGE
