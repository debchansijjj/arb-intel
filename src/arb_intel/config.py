"""Centralised pydantic-settings configuration.

Все секции вложенные через ``__`` (двойное подчёркивание) — стандартный
синтаксис pydantic-settings, удобно мапится на env и .env.example.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# ---------------- storage ----------------
class DBSettings(BaseModel):
    dsn: str = "postgresql+asyncpg://arb:arb@localhost:5432/arb_intel"
    pool_size: int = 20
    max_overflow: int = 10
    echo: bool = False
    statement_timeout_ms: int = 15_000


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"
    namespace: str = "arb_intel"
    socket_timeout_s: float = 2.0


class BusSettings(BaseModel):
    backend: Literal["redis_streams", "nats"] = "redis_streams"
    max_len: int = 200_000
    nats_servers: list[str] = Field(default_factory=lambda: ["nats://nats:4222"])


# ---------------- chains ----------------
class EvmChainEndpoint(BaseModel):
    # NoDecode: env-source НЕ парсит как JSON; ниже валидатор разбирает CSV.
    wss: Annotated[list[str], NoDecode] = Field(default_factory=list)
    https: Annotated[list[str], NoDecode] = Field(default_factory=list)
    chain_id: int = 0
    name: str = ""

    @field_validator("wss", "https", mode="before")
    @classmethod
    def split_csv(cls, v: object) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, Sequence):
            return [str(x) for x in v]
        return []


class EvmSettings(BaseModel):
    ethereum: EvmChainEndpoint = Field(default_factory=lambda: EvmChainEndpoint(name="ethereum", chain_id=1))
    base: EvmChainEndpoint = Field(default_factory=lambda: EvmChainEndpoint(name="base", chain_id=8453))
    arbitrum: EvmChainEndpoint = Field(default_factory=lambda: EvmChainEndpoint(name="arbitrum", chain_id=42161))
    bsc: EvmChainEndpoint = Field(default_factory=lambda: EvmChainEndpoint(name="bsc", chain_id=56))

    def by_name(self, name: str) -> EvmChainEndpoint | None:
        return getattr(self, name, None)


class SolanaSettings(BaseModel):
    rpc_https: str = "https://api.mainnet-beta.solana.com"
    rpc_wss: str = "wss://api.mainnet-beta.solana.com"
    yellowstone_grpc: str | None = None
    yellowstone_token: str | None = None
    helius_api_key: str | None = None
    commitment: Literal["processed", "confirmed", "finalized"] = "confirmed"


class ChainsSettings(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: ["solana", "base", "arbitrum", "bsc", "ethereum"])


# ---------------- domain ----------------
class DiscoverySettings(BaseModel):
    dexscreener_base: AnyUrl = AnyUrl("https://api.dexscreener.com/latest")
    geckoterminal_base: AnyUrl = AnyUrl("https://api.geckoterminal.com/api/v2")
    bootstrap_interval_s: int = 300
    max_tokens_per_chain: int = 5000
    min_liquidity_usd: float = 5_000
    min_volume_24h_usd: float = 25_000


class ArbSettings(BaseModel):
    min_net_profit_usd: float = 4.0
    min_spread_bps: int = 25
    max_notional_usd: float = 2000.0
    sim_sizes_usd: list[float] = Field(default_factory=lambda: [100.0, 500.0, 1000.0])
    min_confidence: float = 0.55
    cross_chain_enabled: bool = True
    cross_chain_min_net_profit_usd: float = 25.0
    fresh_pool_window_s: int = 60 * 60 * 6  # 6h
    fresh_warmup_s: int = 30                 # «прогрев» нового пула перед скан-проверкой
    scanner_interval_s: int = 8              # период полного периодического обхода
    refresh_interval_s: int = 12             # период multicall-refresh пулов
    lag_window_s: int = 90


class TelegramSettings(BaseModel):
    bot_token: str | None = None
    chat_ids: list[int] = Field(default_factory=list)
    cooldown_s: int = 180
    min_confidence: float = 0.6
    min_net_profit_usd: float = 8.0
    blacklist: list[str] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    rate_per_minute: int = 25


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    metrics_enabled: bool = True


# ---------------- root ----------------
class ArbIntelSettings(BaseSettings):
    """Root settings; loaded from env vars with prefix ``ARB_INTEL_``."""

    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    db: DBSettings = Field(default_factory=DBSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    bus: BusSettings = Field(default_factory=BusSettings)
    chains: ChainsSettings = Field(default_factory=ChainsSettings)
    evm: EvmSettings = Field(default_factory=EvmSettings)
    solana: SolanaSettings = Field(default_factory=SolanaSettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    arb: ArbSettings = Field(default_factory=ArbSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    model_config = SettingsConfigDict(
        env_prefix="ARB_INTEL_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> ArbIntelSettings:
    return ArbIntelSettings()
