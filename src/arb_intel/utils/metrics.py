"""Prometheus-метрики, единый реестр."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

events_seen = Counter(
    "arb_events_seen_total",
    "Number of chain events processed",
    labelnames=("chain", "kind"),
    registry=REGISTRY,
)

pools_tracked = Gauge(
    "arb_pools_tracked",
    "Number of pools currently tracked in hot state",
    labelnames=("chain", "dex"),
    registry=REGISTRY,
)

opportunities_found = Counter(
    "arb_opportunities_found_total",
    "Arbitrage opportunities discovered (pre-filter)",
    labelnames=("kind",),
    registry=REGISTRY,
)

alerts_sent = Counter(
    "arb_alerts_sent_total",
    "Telegram alerts dispatched",
    labelnames=("kind",),
    registry=REGISTRY,
)

scanner_loop_latency = Histogram(
    "arb_scanner_loop_latency_seconds",
    "Per-iteration latency of the arbitrage scanner",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)

simulator_latency = Histogram(
    "arb_simulator_latency_seconds",
    "Per-candidate simulation latency",
    buckets=(0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
    registry=REGISTRY,
)

ws_reconnects = Counter(
    "arb_ws_reconnects_total",
    "Websocket reconnections",
    labelnames=("chain", "endpoint"),
    registry=REGISTRY,
)
