# arb-intel

Production-grade cross-chain / cross-DEX **arbitrage intelligence system**.
Не сравнивает «отображаемые» цены — отслеживает изменения **состояния пулов**
(`reserves`, `sqrtPriceX96`, ticks, DLMM bins) и ловит **временные
рассинхронизации** между пулами быстрее, чем агрегаторы.

## Целевые сети
Solana, Base, Arbitrum, BSC, Ethereum (+ архитектурно открытое расширение
на Hyperliquid / Sui / Aptos / Sonic).

## Стек

- Python 3.12, asyncio, FastAPI, aiogram v3
- SQLAlchemy 2 (async) + asyncpg + Alembic
- Redis (hot state + Streams event bus)
- web3.py + multicall3, `eth_subscribe('logs')`
- solders / solana.py + Yellowstone gRPC (опционально Helius)
- Docker / docker-compose

Опциональный нативный модуль для V3 math и парсинга state-аккаунтов
(`rust_ext/`) подключается через `pyo3`, без него используется чистый Python.

## Архитектурные принципы

1. **Track state, not price.** Считаем implied price из reserves / sqrtPrice
   и реагируем на дельту состояния, а не на котировки агрегаторов.
2. **Lag detection.** Один пул уже двинулся, второй ещё стоит — это и есть
   главное окно. Считаем «pool lag probability» как фичу скоринга.
3. **Realistic execution.** Каждое окно прогоняется через симулятор:
   slippage по глубине, fee, gas, priority fee, bridge fee, taxes.
4. **Anti-fake first.** Wallet diversity, tx timing, LP concentration,
   reserve consistency, fake-volume scoring.
5. **Modular workers.** Discovery / Tracker(EVM|Sol) / Scanner / Alerts —
   независимые async-сервисы поверх Redis Streams.

## Быстрый старт

```bash
cp .env.example .env
# заполни telegram bot token, RPC endpoints, helius/yellowstone (опционально)
docker compose up --build
```

После старта:
- API:        http://localhost:8080
- Healthcheck: http://localhost:8080/healthz
- Metrics:    http://localhost:8080/metrics
- Postgres:   `localhost:5432` (arb / arb / arb_intel)
- Redis:      `localhost:6379`

## Layout

```
src/arb_intel/
  config.py         — pydantic-settings, multi-chain config
  db/               — SQLAlchemy models + миграции
  cache/            — redis hot-state, dedup, cooldowns
  bus/              — event bus (redis_streams | nats)
  chains/
    evm/            — web3 client, multicall, ws subscribe, DEX adapters
    solana/         — geyser/yellowstone, layouts (Raydium/Orca/Meteora/PumpSwap)
  discovery/        — DexScreener/GeckoTerminal + on-chain discovery
  tracking/         — liquidity state diffing, lag detector
  arbitrage/        — engine: cross-DEX, cross-chain, lagging, fresh
  simulation/       — V2/V3 math, slippage, gas, bridges
  scoring/          — multi-factor confidence
  heuristics/       — anti-fake (honeypot, wash, LP concentration)
  telegram/         — aiogram-based alerts
  api/              — FastAPI control plane
  workers/          — runnable services
```

## CLI

- `arb-intel api` — поднять FastAPI control plane
- `arb-intel-worker discovery` — universe bootstrap + on-chain discovery
- `arb-intel-worker tracker-evm` — EVM ws + multicall liquidity tracker
- `arb-intel-worker tracker-solana` — Solana geyser/ws tracker
- `arb-intel-worker scanner` — арбитражный движок + симуляция
- `arb-intel-worker alerts` — Telegram bot

## Расширения

- `rust_ext/` — заглушка под нативный V3 tick traversal / SOL layout decode
  через `pyo3`. Включается, когда профайл укажет узкое место.
- Авто-исполнение, MEV-protection, private RPC и mempool-monitoring заложены
  в архитектуре сигналов и могут быть добавлены отдельным executor-воркером.
