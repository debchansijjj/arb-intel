"""Форматтер telegram-алёрта.

Возвращает MarkdownV2-friendly строку. Не делает HTML-escape: aiogram
parse_mode="Markdown" достаточен для нашего набора символов.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote_plus

_CHAIN_EXPLORER = {
    "ethereum": "https://etherscan.io",
    "base": "https://basescan.org",
    "arbitrum": "https://arbiscan.io",
    "bsc": "https://bscscan.com",
    "solana": "https://solscan.io",
}


def _explorer_pool(chain: str, addr: str) -> str:
    base = _CHAIN_EXPLORER.get(chain, "https://etherscan.io")
    if chain == "solana":
        return f"{base}/account/{addr}"
    return f"{base}/address/{addr}"


def _explorer_token(chain: str, addr: str) -> str:
    base = _CHAIN_EXPLORER.get(chain, "https://etherscan.io")
    if chain == "solana":
        return f"{base}/token/{addr}"
    return f"{base}/token/{addr}"


def _dexscreener(chain: str, pair: str) -> str:
    return f"https://dexscreener.com/{chain}/{quote_plus(pair)}"


def format_alert(opp: dict) -> str:
    base = opp["base_token"]
    quote = opp["quote_token"]
    cb = opp["chain_buy"]
    cs = opp["chain_sell"]
    bp = opp["buy_pool"]
    sp = opp["sell_pool"]
    bdex = opp.get("buy_dex", "?")
    sdex = opp.get("sell_dex", "?")
    spread_bps = float(opp.get("spread_bps", 0))
    net = float(opp.get("net_profit_usd", 0))
    gross = float(opp.get("gross_profit_usd", 0))
    size = float(opp.get("best_size_usd", 0))
    slip = float(opp.get("avg_slippage_bps", 0))
    gas = float(opp.get("gas_usd", 0))
    bridge = float(opp.get("bridge_usd", 0))
    eta = opp.get("bridge_eta_s")
    conf = float(opp.get("confidence", 0))
    kind = opp.get("kind", "?")
    ts = float(opp.get("ts", 0))
    when = datetime.fromtimestamp(ts or 0, tz=UTC).strftime("%H:%M:%S UTC")

    cross_chain_line = ""
    if cb != cs:
        cross_chain_line = f"🌉 *Bridge:* `${bridge:.2f}`"
        if eta:
            cross_chain_line += f" eta {int(eta)}s"
        cross_chain_line += "\n"

    fake_reasons = opp.get("fake_reasons") or []
    flag_line = ""
    if fake_reasons:
        flag_line = f"⚠️ *Flags:* {', '.join(fake_reasons[:3])}\n"

    lines = [
        f"💎 *Arb {kind.upper()}* `{conf*100:.0f}%`",
        f"🪙 base `{_short(base)}` / quote `{_short(quote)}`",
        f"🟢 *BUY*  on `{bdex}` / `{cb}`  → {_dexscreener(cb, bp)}",
        f"🔴 *SELL* on `{sdex}` / `{cs}`  → {_dexscreener(cs, sp)}",
        f"📈 *Spread:* `{spread_bps:.0f}bps`   *Slippage:* `{slip:.0f}bps`",
        f"💰 *Net:* `${net:.2f}` (gross `${gross:.2f}`, size `${size:.0f}`)",
        f"⛽ *Gas:* `${gas:.2f}`",
    ]
    if cross_chain_line:
        lines.append(cross_chain_line.rstrip("\n"))
    if flag_line:
        lines.append(flag_line.rstrip("\n"))
    lines.append(f"🕒 {when}")
    lines.append(f"🔗 [buy pool]({_explorer_pool(cb, bp)})  [sell pool]({_explorer_pool(cs, sp)})")
    return "\n".join(lines)


def _short(addr: str) -> str:
    if not addr:
        return "?"
    if len(addr) <= 14:
        return addr
    return f"{addr[:6]}…{addr[-4:]}"


def fingerprint(opp: dict) -> str:
    return ":".join([
        str(opp.get("kind")),
        str(opp.get("buy_pool")),
        str(opp.get("sell_pool")),
        str(opp.get("base_token")),
    ])
