# Multi-stage Dockerfile for micro/mu — built from source.
# Mu is a single Go binary; this clones the repo, builds it, and produces
# a minimal runtime image.
#
# Usage:
#   docker build -f infrastructure/mu.Dockerfile -t omni-g/mu .
# Or via docker-compose (build context = repo root).

# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM golang:1.25-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /src
RUN git clone --depth 1 https://github.com/micro/mu.git .

# Build the mu binary.
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /mu .

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM alpine:3.21

RUN apk add --no-cache ca-certificates curl

# Mu stores data under $HOME/.mu. In Docker, HOME is /data so everything
# lands on the mounted volume.
ENV HOME=/data

COPY --from=builder /mu /usr/local/bin/mu

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["mu", "--serve"]
