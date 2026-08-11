"""E2E provenance pipeline validation (V4 Track 1 + Track 2).

Validates the three roadmap assertions from docs/V4/UI_uplift_roadmapV4.md
Phase 4 without requiring a running browser:

1. Stale canvas state is purged upon query change — verified via the
   SearchResponse contract: a new /search call returns a fresh `nodes`
   array with no carry-over from prior queries.
2. Every rendered node displays a human-readable title and source tag —
   verified by asserting every node in the response carries a non-empty
   `entity_name` and `source.source_name`.
3. Clicking a node opens source trace evidence with matching document
   snippets — verified by asserting each node's `raw_context.snippet_text`
   is a substring of (or matched by) one of the returned `context_units`
   texts, and that no UUIDs leak into the snippet.

These tests run against the Processor FastAPI app via TestClient with
mocked Neo4j/Qdrant, so they exercise the full /search handler including
the V4 `_build_custom_nodes` helper and τ pruning without external deps.
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.processor.config import Settings
from src.processor.main import create_app
from src.retrieval.scored_context import ScoredContext

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _scored(context_id: str, text: str, entity_ids: list[str], score: float = 0.9) -> ScoredContext:
    """Build a ScoredContext for the calibrator mock."""
    return ScoredContext(
        context_id=context_id,
        score=score,
        text=text,
        entity_ids=entity_ids,
    )


@pytest.fixture()
def mock_neo4j_with_provenance() -> MagicMock:
    """Mock Neo4j returning entities + context units with V4 provenance fields."""
    mock_driver = MagicMock()
    mock_driver.close = AsyncMock()
    mock_session = AsyncMock()

    async def side_effect_run(query: str, *args: Any, **kwargs: Any) -> MagicMock:
        mock_result = AsyncMock()
        query_upper = query.upper()

        if "MATCH (E:ENTITY) WHERE E.ID IN $IDS" in query_upper:
            # Return only the entities whose IDs were requested, so stale
            # nodes from a prior query do not leak into a new query's response.
            requested_ids = set(kwargs.get("ids", []))
            all_entities = [
                {
                    "e": {
                        "id": "hospital_123",
                        "type": "FACILITY",
                        "name": "Johns Hopkins Hospital",
                        "description": "Cancer hospital",
                        "confidence": 0.95,
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
            ]
            mock_result.data.return_value = [
                e for e in all_entities if e["e"]["id"] in requested_ids
            ]
        else:
            mock_result.data.return_value = []

        return mock_result

    mock_session.run = side_effect_run
    mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_driver


def _make_settings() -> Settings:
    return Settings(
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


def test_every_node_carries_human_readable_title_and_source_tag(
    mock_neo4j_with_provenance: MagicMock,
) -> None:
    """Roadmap assertion 2: every node has a non-empty title + source tag."""
    app = create_app(_make_settings())
    client = TestClient(app)

    # Calibrated context units that the fusion/calibration path would produce.
    calibrated_contexts = [
        _scored("ctx_123", "Johns Hopkins Hospital treats oncology patients.", ["hospital_123"], 0.99),
        _scored("ctx_456", "Dr. Smith works in the Oncology Department.", ["dr_smith"], 0.85),
    ]

    with (
        patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_neo4j_with_provenance),
        patch("qdrant_client.AsyncQdrantClient", return_value=AsyncMock()),
        patch("src.retrieval.relational.RelationalRetriever.retrieve", return_value=[]),
        patch("src.retrieval.temporal.TemporalRetriever.retrieve", return_value=[]),
        patch("src.indexers.vector.ContextUnitIndexer.encode", return_value=AsyncMock()),
        patch("src.calibration.calibrator.EvidenceCalibrator.calibrate", return_value=calibrated_contexts),
        patch("src.graph.persistence.GraphPersistenceService.search_entities", return_value=[]),
        patch("src.graph.persistence.GraphPersistenceService.fetch_neighbor_entities", return_value=[]),
        patch(
            "src.graph.persistence.GraphPersistenceService.fetch_relationships_for_entities",
            return_value=[],
        ),
    ):
        response = client.post(
            "/search",
            json={"query": "Johns Hopkins", "tenant_id": "default", "limit": 10},
        )
        assert response.status_code == 200
        data = response.json()
        nodes = data.get("nodes", [])
        assert len(nodes) >= 2, "expected at least 2 nodes in response"

        for node in nodes:
            # Assertion 2a: human-readable title
            assert node["entity_name"], f"node {node['id']} has empty entity_name"
            assert node["entity_name"] != node["id"], (
                f"node {node['id']} entity_name is a raw ID, not human-readable"
            )
            # Assertion 2b: source tag
            source = node["source"]
            assert source["source_name"], (
                f"node {node['id']} has empty source_name"
            )
            assert source["source_name"] != "unknown", (
                f"node {node['id']} source_name defaulted to 'unknown'"
            )


def test_clicking_node_opens_matching_snippet(
    mock_neo4j_with_provenance: MagicMock,
) -> None:
    """Roadmap assertion 3: node raw_context snippet matches a returned context unit."""
    app = create_app(_make_settings())
    client = TestClient(app)

    calibrated_contexts = [
        _scored("ctx_123", "Johns Hopkins Hospital treats oncology patients.", ["hospital_123"], 0.99),
    ]

    with (
        patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_neo4j_with_provenance),
        patch("qdrant_client.AsyncQdrantClient", return_value=AsyncMock()),
        patch("src.retrieval.relational.RelationalRetriever.retrieve", return_value=[]),
        patch("src.retrieval.temporal.TemporalRetriever.retrieve", return_value=[]),
        patch("src.indexers.vector.ContextUnitIndexer.encode", return_value=AsyncMock()),
        patch("src.calibration.calibrator.EvidenceCalibrator.calibrate", return_value=calibrated_contexts),
        patch("src.graph.persistence.GraphPersistenceService.search_entities", return_value=[]),
        patch("src.graph.persistence.GraphPersistenceService.fetch_neighbor_entities", return_value=[]),
        patch(
            "src.graph.persistence.GraphPersistenceService.fetch_relationships_for_entities",
            return_value=[],
        ),
    ):
        response = client.post(
            "/search",
            json={"query": "Johns Hopkins", "tenant_id": "default", "limit": 10},
        )
        assert response.status_code == 200
        data = response.json()
        nodes = data.get("nodes", [])
        context_units = data.get("context_units", [])

        hospital_node = next((n for n in nodes if n["id"] == "hospital_123"), None)
        assert hospital_node is not None, "hospital_123 node missing from response"

        # The node's raw_context snippet must match a returned context unit text.
        assert hospital_node["raw_context"] is not None, (
            "hospital_123 node has no raw_context"
        )
        snippet = hospital_node["raw_context"]["snippet_text"]
        matching_ctx = next(
            (c for c in context_units if snippet[:50] in c["text"]),
            None,
        )
        assert matching_ctx is not None, (
            f"node snippet '{snippet[:50]}...' does not match any context unit"
        )

        # No UUIDs should leak into the snippet text.
        assert not _UUID_RE.search(snippet), (
            f"UUID found in snippet text: {snippet}"
        )


def test_stale_canvas_purged_on_new_query(
    mock_neo4j_with_provenance: MagicMock,
) -> None:
    """Roadmap assertion 1: a new /search returns a fresh nodes array (no carry-over).

    The Zustand store's clearCanvas() runs before executeQuery; on the backend
    this manifests as each /search response containing only the nodes for the
    current query, never merged with prior results.
    """
    app = create_app(_make_settings())
    client = TestClient(app)

    first_contexts = [
        _scored("ctx_A", "First query result about hospitals.", ["hospital_123"]),
    ]
    second_contexts = [
        _scored("ctx_B", "Second query result about doctors.", ["dr_smith"]),
    ]

    with (
        patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_neo4j_with_provenance),
        patch("qdrant_client.AsyncQdrantClient", return_value=AsyncMock()),
        patch("src.retrieval.relational.RelationalRetriever.retrieve", return_value=[]),
        patch("src.retrieval.temporal.TemporalRetriever.retrieve", return_value=[]),
        patch("src.indexers.vector.ContextUnitIndexer.encode", return_value=AsyncMock()),
        patch("src.graph.persistence.GraphPersistenceService.search_entities", return_value=[]),
        patch("src.graph.persistence.GraphPersistenceService.fetch_neighbor_entities", return_value=[]),
        patch(
            "src.graph.persistence.GraphPersistenceService.fetch_relationships_for_entities",
            return_value=[],
        ),
    ):
        # First query — returns hospital node
        with patch(
            "src.calibration.calibrator.EvidenceCalibrator.calibrate",
            return_value=first_contexts,
        ):
            r1 = client.post(
                "/search",
                json={"query": "hospital", "tenant_id": "default", "limit": 10},
            )
            assert r1.status_code == 200
            nodes1 = r1.json().get("nodes", [])
            ids1 = {n["id"] for n in nodes1}
            assert "hospital_123" in ids1

        # Second query — returns doctor node only; hospital must NOT carry over
        with patch(
            "src.calibration.calibrator.EvidenceCalibrator.calibrate",
            return_value=second_contexts,
        ):
            r2 = client.post(
                "/search",
                json={"query": "doctor", "tenant_id": "default", "limit": 10},
            )
            assert r2.status_code == 200
            nodes2 = r2.json().get("nodes", [])
            ids2 = {n["id"] for n in nodes2}

        # Stale node from query 1 must not appear in query 2's response
        assert "hospital_123" not in ids2, (
            "stale node 'hospital_123' carried over into second query"
        )
        assert "dr_smith" in ids2, "expected 'dr_smith' in second query results"


def test_zero_mem_invariant_no_llm_tokens_consumed(
    mock_neo4j_with_provenance: MagicMock,
) -> None:
    """V4 zero-mem invariant: graph expansion consumes 0 LLM memory tokens."""
    app = create_app(_make_settings())
    client = TestClient(app)

    with (
        patch("neo4j.AsyncGraphDatabase.driver", return_value=mock_neo4j_with_provenance),
        patch("qdrant_client.AsyncQdrantClient", return_value=AsyncMock()),
        patch("src.retrieval.relational.RelationalRetriever.retrieve", return_value=[]),
        patch("src.retrieval.temporal.TemporalRetriever.retrieve", return_value=[]),
        patch("src.indexers.vector.ContextUnitIndexer.encode", return_value=AsyncMock()),
        patch("src.calibration.calibrator.EvidenceCalibrator.calibrate", return_value=[]),
        patch("src.graph.persistence.GraphPersistenceService.search_entities", return_value=[]),
        patch("src.graph.persistence.GraphPersistenceService.fetch_neighbor_entities", return_value=[]),
        patch(
            "src.graph.persistence.GraphPersistenceService.fetch_relationships_for_entities",
            return_value=[],
        ),
    ):
        response = client.post(
            "/search",
            json={"query": "test", "tenant_id": "default", "limit": 10},
        )
        assert response.status_code == 200
        assert response.json().get("total_tokens_consumed") == 0
