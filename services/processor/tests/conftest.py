from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.processor.config import Settings
from src.processor.main import create_app


@pytest.fixture()
def test_settings() -> Settings:
    """Minimal settings for unit tests — no real infrastructure required."""
    return Settings(
        LOG_LEVEL="debug",
        HTTP_PORT=8001,
        KAFKA_BROKERS="localhost:9092",
        REDIS_URL="redis://localhost:6379",
        NEO4J_URL="neo4j://localhost:7687",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD="test",
        QDRANT_URL="http://localhost:6333",
        OLLAMA_URL="http://localhost:11434",
    )


@pytest.fixture()
def client(test_settings: Settings) -> TestClient:
    """FastAPI test client wired to test settings."""
    app = create_app(test_settings)
    return TestClient(app)


@pytest.fixture()
def mock_redis() -> MagicMock:
    """Mock Redis client for deduplication tests."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.set.return_value = True
    return mock


@pytest.fixture()
def mock_neo4j_driver() -> MagicMock:
    """Mock Neo4j driver for graph persistence tests."""
    mock = MagicMock()
    mock.session.return_value.__enter__ = MagicMock(return_value=MagicMock())
    mock.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.fixture()
def mock_kafka_consumer() -> MagicMock:
    """Mock Kafka consumer for pipeline tests."""
    mock = MagicMock()
    mock.messages.return_value = iter([])
    return mock


@pytest.fixture()
def mock_llm_extractor() -> AsyncMock:
    """Mock LLM extractor that returns an empty result."""
    from src.models.stix import ExtractionResult

    mock = AsyncMock()
    mock.extract.return_value = ExtractionResult(
        source_event_id="test-id",
        extraction_confidence=0.9,
    )
    return mock
