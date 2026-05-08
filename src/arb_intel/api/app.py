"""FastAPI control-plane.

Лёгкий API для observability и ручного управления:
  GET  /health
  GET  /metrics
  GET  /pools/{chain}
  GET  /opportunities/recent
  GET  /universe
  POST /universe/promote/{token_id}
  POST /alerts/test
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import desc, select
from starlette.responses import Response

from arb_intel.config import get_settings
from arb_intel.db.models import Alert, Opportunity, Pool, UniverseMembership
from arb_intel.db.session import dispose, session_scope
from arb_intel.logging import configure_logging, get_logger
from arb_intel.tracking.pool_state import iter_all
from arb_intel.utils.metrics import REGISTRY

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    yield
    await dispose()


app = FastAPI(title="arb-intel", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "env": get_settings().env}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/pools/{chain}")
async def pools(chain: str, limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = 0
    async for p in iter_all(chain):
        out.append({
            "chain": p.chain, "pool": p.pool, "dex": p.dex, "kind": p.kind,
            "token0": p.token0, "token1": p.token1,
            "implied_price": p.implied_price, "tvl_usd": p.tvl_usd,
            "ts": p.ts, "block": p.block, "slot": p.slot,
        })
        n += 1
        if n >= limit:
            break
    return out


@app.get("/opportunities/recent")
async def opp_recent(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    async with session_scope() as sess:
        rows = (
            await sess.execute(
                select(Opportunity).order_by(desc(Opportunity.created_at)).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": r.id, "kind": r.kind, "spread_bps": r.spread_bps,
            "net_profit_usd": r.net_profit_usd, "score": r.score, "confidence": r.confidence,
            "payload": r.payload, "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.get("/alerts/recent")
async def alerts_recent(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    async with session_scope() as sess:
        rows = (
            await sess.execute(select(Alert).order_by(desc(Alert.sent_at)).limit(limit))
        ).scalars().all()
    return [
        {"id": r.id, "fingerprint": r.fingerprint, "chat_id": r.chat_id,
         "sent_at": r.sent_at.isoformat() if r.sent_at else None, "payload": r.payload}
        for r in rows
    ]


@app.get("/universe")
async def universe(tier: int | None = None, limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
    async with session_scope() as sess:
        stmt = select(UniverseMembership).order_by(desc(UniverseMembership.score)).limit(limit)
        if tier is not None:
            stmt = stmt.where(UniverseMembership.tier == tier)
        rows = (await sess.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "token_id": r.token_id, "tier": r.tier, "score": r.score,
         "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
         "expires_at": r.expires_at.isoformat() if r.expires_at else None,
         "reason": r.reason}
        for r in rows
    ]


@app.post("/universe/promote/{token_id}")
async def promote(token_id: int, tier: int = Query(..., ge=1, le=3)) -> dict[str, Any]:
    if tier not in (1, 2, 3):
        raise HTTPException(400, "tier must be 1..3")
    async with session_scope() as sess:
        from arb_intel.db.repositories import upsert_universe
        await upsert_universe(sess, token_id, tier=tier, score=100.0, reason="api:manual")
    return {"ok": True, "token_id": token_id, "tier": tier}


@app.get("/pools-count/{chain}")
async def pools_count(chain: str) -> dict[str, Any]:
    n = 0
    async for _p in iter_all(chain):
        n += 1
    return {"chain": chain, "count": n}


@app.get("/pools-db")
async def pools_db(limit: int = Query(100, ge=1, le=2000)) -> list[dict[str, Any]]:
    async with session_scope() as sess:
        rows = (
            await sess.execute(select(Pool).order_by(desc(Pool.first_seen_at)).limit(limit))
        ).scalars().all()
    return [
        {"id": r.id, "chain_id": r.chain_id, "address": r.address, "dex": r.dex, "kind": r.kind,
         "fee_bps": r.fee_bps,
         "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None}
        for r in rows
    ]
