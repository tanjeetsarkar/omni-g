from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = Field(default="info", alias="LOG_LEVEL")
    http_port: int = Field(default=8001, alias="HTTP_PORT")

    # Kafka
    kafka_brokers: str = Field(default="localhost:9092", alias="KAFKA_BROKERS")
    kafka_group_id: str = Field(default="processor-group", alias="KAFKA_GROUP_ID")
    kafka_raw_topic: str = Field(default="raw-feed", alias="KAFKA_RAW_TOPIC")
    kafka_entities_topic: str = Field(default="processed-entities", alias="KAFKA_ENTITIES_TOPIC")
    kafka_alerts_topic: str = Field(default="analyst-alerts", alias="KAFKA_ALERTS_TOPIC")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    dedup_ttl_seconds: int = Field(default=86400, alias="DEDUP_TTL_SECONDS")

    # Neo4j
    neo4j_url: str = Field(default="neo4j://localhost:7687", alias="NEO4J_URL")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="omni-g-password", alias="NEO4J_PASSWORD")

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    # LLM
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="qwen2.5:3b", alias="OLLAMA_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")


def get_settings() -> Settings:
    return Settings()
