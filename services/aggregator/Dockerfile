# ============================================================
# Stage 1: Builder
# ============================================================
FROM golang:1.26-bookworm AS builder

# confluent-kafka-go requires librdkafka headers at compile time.
RUN apt-get update && apt-get install -y --no-install-recommends \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Cache dependency downloads before copying source.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=1 GOOS=linux go build \
    -ldflags="-s -w" \
    -o /aggregator ./cmd/aggregator

# ============================================================
# Stage 2: Runtime
# ============================================================
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    librdkafka1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root.
RUN useradd --uid 1001 --create-home appuser
USER appuser

WORKDIR /app
COPY --from=builder /aggregator ./aggregator

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./aggregator"]
