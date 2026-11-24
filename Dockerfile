# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Test image: same deps + pytest. `make test` runs it.
FROM builder AS test
RUN uv sync --frozen --no-editable
COPY config ./config
COPY templates ./templates
COPY tests ./tests
ENV DAVIDTIMES_ROOT=/app
CMD ["/app/.venv/bin/pytest", "-q"]

FROM python:3.12-slim AS runtime
ENV TZ=America/Bogota \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DAVIDTIMES_ROOT=/app \
    DAVIDTIMES_CACHE_DIR=/data
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data /app/dist && chown app:app /data /app/dist
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY config ./config
COPY templates ./templates
USER app
ENTRYPOINT ["davidtimes"]
CMD ["build"]
