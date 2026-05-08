from __future__ import annotations

from arb_intel.simulation.bridges import bridge_cost, is_cross_chain_supported
from arb_intel.simulation.gas import PROFILES, estimate_gas_usd, update_profile


def test_estimate_gas_usd_known_chains() -> None:
    for chain in ("ethereum", "base", "arbitrum", "bsc", "solana"):
        v = estimate_gas_usd(chain)
        assert v >= 0


def test_estimate_gas_unknown_chain_returns_default() -> None:
    assert estimate_gas_usd("nonexistent") == 1.0


def test_update_profile_updates_value() -> None:
    update_profile("base", priority_gwei=0.5)
    assert PROFILES["base"].priority_gwei == 0.5


def test_bridge_cost_supported() -> None:
    assert is_cross_chain_supported("base", "arbitrum")
    bc = bridge_cost("base", "arbitrum", 1000.0)
    assert bc is not None
    assert bc.flat_usd > 0
    assert bc.eta_s > 0


def test_bridge_cost_same_chain_is_none() -> None:
    assert bridge_cost("base", "base", 100.0) is None


def test_bridge_cost_unknown_pair_is_none() -> None:
    assert bridge_cost("base", "nonexistent", 100.0) is None
