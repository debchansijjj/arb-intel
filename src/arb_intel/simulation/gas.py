"""Gas / fee estimator.

Хранит "разумные дефолты" по сетям. Цифры — плавающие, но дают consistent
оценку себестоимости транзакции в USD. В дальнейшем подключаем real-time
fee-oracle (bs gasstation, blocknative, helius priority fee API).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GasProfile:
    chain: str
    base_gas: int                 # газ-юнитов на типичную сделку (роутер swap)
    priority_gwei: float          # приоритетка
    base_fee_gwei: float          # базовый газ
    native_usd: float             # дефолтная цена нативного токена в USD


# Дефолтные профили — переписываются позже из oracle.
PROFILES: dict[str, GasProfile] = {
    "ethereum": GasProfile("ethereum", 250_000, 1.0, 25.0, 3000.0),
    "base": GasProfile("base", 250_000, 0.01, 0.05, 3000.0),
    "arbitrum": GasProfile("arbitrum", 1_500_000, 0.0, 0.1, 3000.0),
    "bsc": GasProfile("bsc", 250_000, 0.0, 1.0, 600.0),
    "solana": GasProfile("solana", 0, 0.0, 0.0, 150.0),
}

# Solana: не gas-units, а priority fee microlamports + signature fee.
# Для простоты возвращаем фиксированный USD per tx.
SOLANA_TX_USD = 0.005


def estimate_gas_usd(chain: str) -> float:
    p = PROFILES.get(chain)
    if not p:
        return 1.0
    if chain == "solana":
        return SOLANA_TX_USD
    total_gwei = p.base_fee_gwei + p.priority_gwei
    eth_used = (p.base_gas * total_gwei) / 1e9
    return eth_used * p.native_usd


def update_profile(chain: str, **kwargs: float | int) -> None:
    cur = PROFILES.get(chain)
    if cur is None:
        return
    PROFILES[chain] = GasProfile(
        chain=chain,
        base_gas=int(kwargs.get("base_gas", cur.base_gas)),
        priority_gwei=float(kwargs.get("priority_gwei", cur.priority_gwei)),
        base_fee_gwei=float(kwargs.get("base_fee_gwei", cur.base_fee_gwei)),
        native_usd=float(kwargs.get("native_usd", cur.native_usd)),
    )
