from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = Field(default="info", alias="LOG_LEVEL")
    http_port: int = Field(default=8001, alias="HTTP_PORT")

    # Kafka
    kafka_enabled: bool = Field(default=False, alias="KAFKA_ENABLED")
    kafka_brokers: str = Field(default="localhost:9092", alias="KAFKA_BROKERS")
    kafka_group_id: str = Field(default="processor-group", alias="KAFKA_GROUP_ID")
    kafka_raw_topic: str = Field(default="raw-feed", alias="KAFKA_RAW_TOPIC")
    kafka_entities_topic: str = Field(default="processed-entities", alias="KAFKA_ENTITIES_TOPIC")
    kafka_alerts_topic: str = Field(default="analyst-alerts", alias="KAFKA_ALERTS_TOPIC")
    kafka_dlq_topic: str = Field(default="raw-feed.dlq", alias="KAFKA_DLQ_TOPIC")
    kafka_num_workers: int = Field(default=1, alias="KAFKA_NUM_WORKERS")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    dedup_ttl_seconds: int = Field(default=86400, alias="DEDUP_TTL_SECONDS")

    # Neo4j
    neo4j_url: str = Field(default="neo4j://localhost:7687", alias="NEO4J_URL")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="omni-g-local-dev", alias="NEO4J_PASSWORD")

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default="omni-g-local-dev", alias="QDRANT_API_KEY")

    # LLM
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="qwen2.5:1.5b", alias="OLLAMA_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # MinIO / S3-compatible object storage
    minio_url: str = Field(default="http://localhost:9000", alias="MINIO_URL")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="omni-g-briefings", alias="MINIO_BUCKET")

    # TTS / Briefing
    kokoro_url: str = Field(default="http://localhost:8880", alias="KOKORO_URL")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    briefing_hour: int = Field(default=8, alias="BRIEFING_HOUR")
    briefing_tenants: str = Field(default="default", alias="BRIEFING_TENANTS")
    briefing_preflight_enabled: bool = Field(
        default=False, alias="BRIEFING_PREFLIGHT_ENABLED"
    )
    briefing_preflight_strict: bool = Field(default=False, alias="BRIEFING_PREFLIGHT_STRICT")


def get_settings() -> Settings:
    return Settings()
