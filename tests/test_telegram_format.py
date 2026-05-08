from __future__ import annotations

from arb_intel.telegram.format import fingerprint, format_alert


def _opp() -> dict:
    return {
        "kind": "cross-dex",
        "chain_buy": "base", "chain_sell": "base",
        "buy_pool": "0x" + "ab" * 20, "sell_pool": "0x" + "cd" * 20,
        "buy_dex": "uniswap_v3", "sell_dex": "aerodrome",
        "base_token": "0x" + "11" * 20, "quote_token": "0x" + "22" * 20,
        "spread_bps": 137.4, "best_size_usd": 500,
        "net_profit_usd": 18.42, "gross_profit_usd": 22.0,
        "gas_usd": 1.21, "bridge_usd": 0.0, "bridge_eta_s": None,
        "avg_slippage_bps": 35.0, "confidence": 0.78,
        "ts": 1700000000, "fake_reasons": [],
    }


def test_format_alert_returns_string_with_key_fields() -> None:
    s = format_alert(_opp())
    assert "Arb" in s
    assert "BUY" in s
    assert "SELL" in s
    assert "Spread" in s
    assert "Net" in s


def test_format_alert_cross_chain_includes_bridge() -> None:
    o = _opp()
    o["chain_buy"] = "base"
    o["chain_sell"] = "arbitrum"
    o["bridge_usd"] = 5.0
    o["bridge_eta_s"] = 90
    s = format_alert(o)
    assert "Bridge" in s
    assert "eta" in s


def test_fingerprint_deterministic() -> None:
    f1 = fingerprint(_opp())
    f2 = fingerprint(_opp())
    assert f1 == f2

    o = _opp()
    o["buy_pool"] = "0xdifferent"
    assert fingerprint(o) != f1
