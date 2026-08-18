# Build stage
FROM golang:1.26-bookworm AS builder

WORKDIR /app

# Install build dependencies (including librdkafka for confluent-kafka-go)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git librdkafka-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy aggregator go.mod and go.sum for replace directive
COPY go.mod go.sum ./

# Copy plugin go.mod and go.sum
COPY plugins/newsearch/go.mod plugins/newsearch/go.sum ./plugins/newsearch/

# Copy ALL aggregator packages that plugin depends on (including internal ones)
COPY pkg/ ./pkg/
COPY internal/ ./internal/

# Copy plugin source
COPY plugins/newsearch/ ./plugins/newsearch/

# Download dependencies for the plugin
WORKDIR /app/plugins/newsearch
RUN go mod download

# Build the plugin (CGO enabled for confluent-kafka-go)
RUN CGO_ENABLED=1 GOOS=linux go build -o /app/newsearch .

# Runtime stage
FROM debian:bookworm-slim

WORKDIR /app

# Install ca-certificates and librdkafka for runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates librdkafka1 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN adduser --uid 1001 --disabled-password --gecos "" appuser

# Copy binary
COPY --from=builder /app/newsearch .

# Copy config
COPY plugins/newsearch/config.yaml .

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose MCP port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Run
ENTRYPOINT ["./newsearch"]
