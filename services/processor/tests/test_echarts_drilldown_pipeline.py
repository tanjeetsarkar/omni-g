from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.processor.config import Settings
from src.processor.main import create_app


@pytest.fixture()
def mock_neo4j_for_drilldown() -> MagicMock:
    """Mock Neo4j session and driver return data for the multi-hop expand pipeline."""
    mock_driver = MagicMock()
    mock_driver.close = AsyncMock()
    mock_session = AsyncMock()

    # We will mock session.run results based on the query executed.
    async def side_effect_run(query: str, *args: list, **kwargs: dict) -> MagicMock:
        mock_result = AsyncMock()

        # Determine query signature
        query_upper = query.upper()
        if (
            "APOC.PATH.SUBGRAPHNODES" in query_upper
            or "APOC.ALGO.PAGERANKWITHCONFIG" in query_upper
        ):
            # Step 1 / 2: apoc pagerank query returning context unit nodes
            mock_result.data.return_value = [
                {
                    "context_id": "ctx_123",
                    "text": "This is raw context about Johns Hopkins Hospital.",
                    "score": 0.99,
                },
                {
                    "context_id": "ctx_456",
                    "text": "Dr. Smith works in the Oncology Dept.",
                    "score": 0.85,
                },
            ]
        elif "CO_OCCURRED_IN" in query_upper and "COLLECT(E.ID)" in query_upper:
            # Step 3: fetch co-occurring entity IDs for those context units
            mock_result.data.return_value = [
                {"context_id": "ctx_123", "entity_ids": ["hospital_123", "dr_smith"]},
                {"context_id": "ctx_456", "entity_ids": ["dr_smith", "trial_2025"]},
            ]
        elif "MATCH (E:ENTITY) WHERE E.ID IN $IDS" in query_upper:
            # Step 4: fetch Entity nodes
            mock_result.data.return_value = [
                {
                    "e": {
                        "id": "hospital_123",
                        "type": "FACILITY",
                        "name": "Johns Hopkins Hospital",
                        "description": "Cancer hospital",
                        "confidence": 0.99,
                        "tenant_id": "default",
                        "source_id": "src-1",
                    }
                },
                {
                    "e": {
                        "id": "dr_smith",
                        "type": "PERSON",
                        "name": "Dr. Smith",
                        "description": "Oncologist",
                        "confidence": 0.85,
                        "tenant_id": "default",
                        "source_id": "src-2",
                    }
                },
                {
                    "e": {
                        "id": "trial_2025",
                        "type": "STUDY",
                        "name": "Immunotherapy Trial 2025",
                        "description": "Clinical Trial",
                        "confidence": 0.75,
                        "tenant_id": "default",
                        "source_id": "src-3",
                    }
                },
            ]
        else:
            # Fallback
            mock_result.data.return_value = []

        return mock_result

    mock_session.run = side_effect_run
    mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_driver


def test_echarts_drilldown_pipeline(mock_neo4j_for_drilldown: MagicMock) -> None:
    """End-to-end integration test validating the ECharts drilldown expansion endpoints.

    1. Triggers search query -> checks retrieved entities
    2. Triggers multi-hop drilldown expansion API query
    3. Verifies zero LLM token consumption in the expansion pipeline
    4. Validates API execution latency is well within < 120ms
    """
    settings = Settings(
        LOG_LEVEL="debug",
        HTTP_PORT=8001,
        KAFKA_BROKERS="localhost:9092",
        REDIS_URL="redis://localhost:6379",
        NEO4J_URL="neo4j://localhost:7687",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD="test",  # noqa: S106
        QDRANT_URL="http://localhost:6333",
        OLLAMA_URL="http://localhost:11434",
    )

    app = create_app(settings)
    client = TestClient(app)

    # Patch the Neo4j AsyncGraphDatabase.driver inside /query/expand to return our mocked driver.
    # We also patch any Qdrant or Indexer instances to isolate the test from external dependencies.
    with (
        patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_neo4j_for_drilldown),
        patch("qdrant_client.AsyncQdrantClient", return_value=AsyncMock()),
        patch("src.retrieval.relational.RelationalRetriever.retrieve", return_value=[]),
        patch("src.retrieval.temporal.TemporalRetriever.retrieve", return_value=[]),
        patch("src.indexers.vector.ContextUnitIndexer.encode", return_value=AsyncMock()),
    ):
        # Measurement 1: Expand endpoint latency & execution test
        start_time = time.perf_counter()

        response = client.post(
            "/query/expand",
            json={
                "anchor_node_id": "hospital_123",
                "current_depth": 1,
                "target_depth": 2,
                "tenant_id": "default",
            },
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Assert successful HTTP request
        assert response.status_code == 200
        data = response.json()

        # Step 1: Assert level 0 root node level 1 level 2 nodes correctly fetched
        entities = data["entities"]
        expect_ids = {"hospital_123", "dr_smith", "trial_2025"}
        retrieved_ids = {e["id"] for e in entities}
        assert expect_ids.issubset(retrieved_ids)

        hospital = next(e for e in entities if e["id"] == "hospital_123")
        assert hospital["name"] == "Johns Hopkins Hospital"
        assert hospital["type"] == "FACILITY"

        # Step 2: Assert level 1 node details are present
        dr_smith = next(e for e in entities if e["id"] == "dr_smith")
        assert dr_smith["name"] == "Dr. Smith"
        assert dr_smith["type"] == "PERSON"

        # Step 3: Assert level 2 node details are present
        trial = next(e for e in entities if e["id"] == "trial_2025")
        assert trial["name"] == "Immunotherapy Trial 2025"
        assert trial["type"] == "STUDY"

        # Step 4: Verify zero indexing / LLM memory tokens were used or logged
        # Expansion queries run purely as traversal / non-generative.
        assert "token" not in data or data.get("tokens", 0) == 0

        # Step 5: Assert backend expansion response latency remains < 120ms
        assert latency_ms < 120.0
