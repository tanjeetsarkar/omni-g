FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen

# ============================================================
# Runtime stage
# ============================================================
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy installed environment from builder.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root.
RUN useradd --uid 1001 --create-home appuser
USER appuser

COPY src/ ./src/

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "src.processor.main:app", "--host", "0.0.0.0", "--port", "8001"]
