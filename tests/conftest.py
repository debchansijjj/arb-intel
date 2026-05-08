"""Общая настройка тестов: изолируем от .env / реального Redis / Postgres.

Все тесты пишут в чистый pydantic-конфиг по умолчанию через очистку
``get_settings.cache_clear`` и переменные окружения, выставленные ниже.
"""

from __future__ import annotations

import os

# Гарантируем, что pydantic-settings не подтянет реальный .env из репо.
os.environ.setdefault("ARB_INTEL_ENV", "dev")
os.environ.setdefault("ARB_INTEL_LOG_LEVEL", "WARNING")
os.environ.setdefault("ARB_INTEL_DB__DSN", "postgresql+asyncpg://x:x@localhost:1/x")
os.environ.setdefault("ARB_INTEL_REDIS__URL", "redis://localhost:1/0")

# pyproject выставляет asyncio_mode=auto — этого достаточно.
