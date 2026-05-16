FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod .
COPY main.go .
RUN go build -o mcp-echo .

FROM alpine:3.19
RUN adduser -D -u 1000 appuser
USER appuser
WORKDIR /app
COPY --from=builder /app/mcp-echo .
EXPOSE 8090
ENV PORT=8090
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost:${PORT}/health || exit 1
ENTRYPOINT ["./mcp-echo"]
