# Aggregator Service

The **Aggregator** is the edge ingestion layer of Omni-G. It receives raw events from MCP (Model Context Protocol) plugins, validates their schema, and produces them onto the `raw-feed` Kafka topic for downstream processing.

## Responsibilities

- **MCP Host** — discovers and polls registered MCP plugin servers (Phase M3.1)
- **Schema Validation** — delegates payload validation to the Processor sidecar before producing
- **Kafka Producer** — delivers validated events to the `raw-feed` topic with retry and batching
- **Observability** — exposes Prometheus metrics at `/metrics` (Phase M3.1)

## Directory Structure

```
aggregator/
├── cmd/
│   └── aggregator/
│       └── main.go          # Entry point
├── internal/
│   ├── config/
│   │   └── config.go        # Viper-based config from env vars
│   ├── kafka/
│   │   └── producer.go      # Kafka producer wrapper
│   ├── server/
│   │   └── server.go        # HTTP server (health, metrics)
│   └── validation/
│       └── validator.go     # Validation sidecar client
├── Dockerfile
├── go.mod
└── README.md
```

## Configuration

All configuration is provided via environment variables.

| Variable                 | Default                      | Description                          |
|--------------------------|------------------------------|--------------------------------------|
| `LOG_LEVEL`              | `info`                       | Zerolog level (trace/debug/info/warn/error) |
| `HTTP_PORT`              | `8080`                       | HTTP server port                     |
| `KAFKA_BROKERS`          | `localhost:9092`             | Comma-separated Kafka bootstrap servers |
| `KAFKA_TOPIC`            | `raw-feed`                   | Destination topic                    |
| `KAFKA_PRODUCER_BATCH_SIZE` | `100`                     | Max messages per batch               |
| `KAFKA_BATCH_TIMEOUT_MS` | `1000`                       | Batch flush timeout (ms)             |
| `VALIDATION_SERVICE_URL` | `http://localhost:8001`      | Processor sidecar URL                |

## Running Locally

```bash
# Install dependencies (requires librdkafka-dev on the host)
go mod download

# Run
go run ./cmd/aggregator

# Test
go test ./...

# Build
go build -o bin/aggregator ./cmd/aggregator
```

## API Endpoints

| Method | Path      | Description                |
|--------|-----------|----------------------------|
| `GET`  | `/health` | Liveness probe             |
| `GET`  | `/ready`  | Readiness probe            |
| `GET`  | `/metrics`| Prometheus metrics (M3.1)  |

## Docker

```bash
docker build -t omni-g/aggregator .
docker run -e KAFKA_BROKERS=kafka:9092 -p 8080:8080 omni-g/aggregator
```
