FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY data/ /app/data/
COPY eval/ /app/eval/
RUN uv sync --frozen --no-dev

ENV CB_DATA_DIR=/app/data EMBED_CACHE=/app/.fastembed_cache PATH="/app/backend/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "claimbridge.cli"]
