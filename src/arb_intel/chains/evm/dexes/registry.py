"""Реестр factory-адресов и DEX-метаданных по сетям.

Не помещаем тут полный список — только активно используемые. Расширяем
через config или через знание универса.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DexFactory:
    chain: str
    dex: str
    kind: str               # v2 | v3 | v4 | aerodrome
    factory: str
    default_fee_bps: int    # v2/aerodrome — 25/30; v3 — берём из лога


# Список не претендует на полноту: добавлять можно из конфига, но базовые
# адреса по mainnet — здесь.
EVM_FACTORIES: list[DexFactory] = [
    # --- Ethereum ---
    DexFactory("ethereum", "uniswap_v2", "v2", "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f", 30),
    DexFactory("ethereum", "uniswap_v3", "v3", "0x1F98431c8aD98523631AE4a59f267346ea31F984", 30),
    DexFactory("ethereum", "sushi_v2", "v2", "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac", 30),
    # --- Base ---
    DexFactory("base", "uniswap_v3", "v3", "0x33128a8fC17869897dcE68Ed026d694621f6FDfD", 30),
    DexFactory("base", "uniswap_v2", "v2", "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", 30),
    DexFactory("base", "aerodrome", "aerodrome", "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", 25),
    # --- Arbitrum ---
    DexFactory("arbitrum", "uniswap_v3", "v3", "0x1F98431c8aD98523631AE4a59f267346ea31F984", 30),
    DexFactory("arbitrum", "sushi_v2", "v2", "0xc35DADB65012eC5796536bD9864eD8773aBc74C4", 30),
    # --- BSC ---
    DexFactory("bsc", "pancake_v2", "v2", "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73", 25),
    DexFactory("bsc", "pancake_v3", "v3", "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", 25),
]


def factories_for(chain: str) -> list[DexFactory]:
    return [f for f in EVM_FACTORIES if f.chain == chain]
