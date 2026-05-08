"""Telegram-бот: получает ranked-opp с шины и шлёт алёрты в чаты.

Особенности:
- aiogram v3 + ratelimit (aiolimiter).
- дедуп через Redis (`fingerprint` + cooldown).
- watchlist / blacklist по символам / адресам / DEX.
- сохраняем `Alert` в БД для аудита.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiolimiter import AsyncLimiter

from arb_intel.bus.streams import Streams, consume
from arb_intel.cache.redis_client import cooldown_ok, dedup
from arb_intel.config import get_settings
from arb_intel.db.models import Alert
from arb_intel.db.session import session_scope
from arb_intel.logging import get_logger
from arb_intel.telegram.format import fingerprint, format_alert
from arb_intel.utils.metrics import alerts_sent

log = get_logger(__name__)


class TelegramAlerter:
    def __init__(self) -> None:
        s = get_settings()
        self._cfg = s.telegram
        if not self._cfg.bot_token:
            raise RuntimeError("ARB_INTEL_TELEGRAM__BOT_TOKEN is required")
        self._bot = Bot(
            token=self._cfg.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._limiter = AsyncLimiter(self._cfg.rate_per_minute, 60)

    async def aclose(self) -> None:
        await self._bot.session.close()

    def _passes_filters(self, opp: dict) -> bool:
        cfg = self._cfg
        # blacklist
        for needle in cfg.blacklist:
            n = needle.lower()
            if n in (opp.get("base_token") or "").lower():
                return False
            if n in (opp.get("quote_token") or "").lower():
                return False
            if n in (opp.get("buy_dex") or "").lower():
                return False
            if n in (opp.get("sell_dex") or "").lower():
                return False
        # watchlist (если задан — пропускаем только match)
        if cfg.watchlist:
            blob = "|".join([
                str(opp.get("base_token") or ""),
                str(opp.get("quote_token") or ""),
                str(opp.get("buy_dex") or ""),
                str(opp.get("sell_dex") or ""),
            ]).lower()
            if not any(w.lower() in blob for w in cfg.watchlist):
                return False
        if float(opp.get("net_profit_usd", 0)) < cfg.min_net_profit_usd:
            return False
        return not float(opp.get("confidence", 0)) < cfg.min_confidence

    async def _persist(self, fp: str, chat_id: int, opp: dict) -> None:
        async with session_scope() as sess:
            sess.add(
                Alert(
                    fingerprint=fp,
                    chat_id=chat_id,
                    payload=opp,
                )
            )

    async def dispatch(self, opp: dict) -> None:
        if not self._passes_filters(opp):
            return
        fp = fingerprint(opp)
        # глобальный дедуп (любой чат)
        if not await dedup(f"alert:{fp}", ttl_s=self._cfg.cooldown_s):
            return
        text = format_alert(opp)
        for chat_id in self._cfg.chat_ids:
            if not await cooldown_ok("tg", f"{chat_id}:{fp}", self._cfg.cooldown_s):
                continue
            async with self._limiter:
                try:
                    await self._bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
                except TelegramRetryAfter as e:
                    log.warning("tg.retry_after", retry=e.retry_after)
                    await asyncio.sleep(e.retry_after + 0.5)
                    continue
                except Exception:
                    log.exception("tg.send_error", chat_id=chat_id)
                    continue
                alerts_sent.labels(kind=opp.get("kind", "unknown")).inc()
                await self._persist(fp, chat_id, opp)


async def run_alert_loop() -> None:
    cfg = get_settings().telegram
    if not cfg.bot_token or not cfg.chat_ids:
        log.warning("tg.disabled", reason="no_bot_token_or_chat_ids")
        # idle, чтобы supervisor не рестартил бесконечно
        await asyncio.Event().wait()
        return
    alerter = TelegramAlerter()
    try:
        async for msg in consume(Streams.OPP_RANKED, group="tg-alerts", consumer="tg-1"):
            try:
                await alerter.dispatch(msg.payload)
            except Exception:
                log.exception("tg.dispatch_error")
    finally:
        await alerter.aclose()
