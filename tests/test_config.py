from __future__ import annotations


def test_settings_defaults_loadable() -> None:
    # late import — чтобы env уже стояли
    from arb_intel.config import get_settings

    s = get_settings()
    assert s.env in ("dev", "staging", "prod")
    assert s.arb.min_confidence > 0
    assert s.arb.sim_sizes_usd
    assert "base" in s.chains.enabled


def test_settings_arb_thresholds_sane() -> None:
    from arb_intel.config import get_settings

    s = get_settings()
    assert 0 < s.arb.min_confidence <= 1
    assert s.arb.min_net_profit_usd >= 0
    assert s.arb.refresh_interval_s > 0
