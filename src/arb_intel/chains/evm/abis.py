"""Минимальные ABI-фрагменты для тех событий, что нам нужны.

Полные ABI не таскаем — только нужные функции/события. Это уменьшает
runtime и упрощает поставку.
"""

from __future__ import annotations

from typing import Any

# ---------------- ERC20 ----------------
ERC20_DECIMALS = "0x313ce567"  # decimals()
ERC20_SYMBOL = "0x95d89b41"    # symbol()
ERC20_NAME = "0x06fdde03"      # name()
ERC20_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()
ERC20_BALANCE_OF = "0x70a08231"    # balanceOf(address)


# ---------------- Uniswap V2 ----------------
# event PairCreated(address indexed token0, address indexed token1, address pair, uint)
PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

# Sync(uint112 reserve0, uint112 reserve1)
SYNC_TOPIC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
# Swap(...): много вариантов; v2 канонический
V2_SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

UNISWAP_V2_FACTORY_ABI: list[dict[str, Any]] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "pair", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "", "type": "uint256"},
        ],
        "name": "PairCreated",
        "type": "event",
    }
]

UNISWAP_V2_PAIR_ABI: list[dict[str, Any]] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "name": "reserve0", "type": "uint112"},
            {"indexed": False, "name": "reserve1", "type": "uint112"},
        ],
        "name": "Sync",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": False, "name": "amount0In", "type": "uint256"},
            {"indexed": False, "name": "amount1In", "type": "uint256"},
            {"indexed": False, "name": "amount0Out", "type": "uint256"},
            {"indexed": False, "name": "amount1Out", "type": "uint256"},
            {"indexed": True, "name": "to", "type": "address"},
        ],
        "name": "Swap",
        "type": "event",
    },
    {
        "constant": True, "inputs": [], "name": "getReserves",
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
        "type": "function",
    },
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "type": "function"},
]


# ---------------- Uniswap V3 ----------------
# PoolCreated(address indexed token0, address indexed token1, uint24 indexed fee, int24 tickSpacing, address pool)
POOL_CREATED_TOPIC = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"

# V3 Swap event:
# Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1,
#      uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
V3_SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

UNISWAP_V3_FACTORY_ABI: list[dict[str, Any]] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "token0", "type": "address"},
            {"indexed": True, "name": "token1", "type": "address"},
            {"indexed": True, "name": "fee", "type": "uint24"},
            {"indexed": False, "name": "tickSpacing", "type": "int24"},
            {"indexed": False, "name": "pool", "type": "address"},
        ],
        "name": "PoolCreated",
        "type": "event",
    }
]

UNISWAP_V3_POOL_ABI: list[dict[str, Any]] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": True, "name": "recipient", "type": "address"},
            {"indexed": False, "name": "amount0", "type": "int256"},
            {"indexed": False, "name": "amount1", "type": "int256"},
            {"indexed": False, "name": "sqrtPriceX96", "type": "uint160"},
            {"indexed": False, "name": "liquidity", "type": "uint128"},
            {"indexed": False, "name": "tick", "type": "int24"},
        ],
        "name": "Swap",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
        "type": "function",
    },
    {
        "inputs": [], "name": "liquidity", "outputs": [{"type": "uint128"}], "type": "function",
    },
    {"inputs": [], "name": "fee", "outputs": [{"type": "uint24"}], "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "type": "function"},
]


# ---------------- multicall3 ----------------
MULTICALL3_ADDR = "0xcA11bde05977b3631167028862bE2a173976CA11"
MULTICALL3_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "payable",
        "type": "function",
    }
]
