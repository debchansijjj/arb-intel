# syntax=docker/dockerfile:1.7
# ----- builder -----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl git pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip wheel \
    && pip wheel --wheel-dir /wheels .[dev]

# ----- runtime -----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    ARB_INTEL_ENV=prod

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 arb

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

RUN pip install --no-index --find-links=/wheels arb-intel[dev] \
    && rm -rf /wheels

USER arb
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["arb-intel"]
