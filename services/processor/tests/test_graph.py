from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.graph.persistence import GraphPersistenceService, _map_relationship_type
from src.graph.schema import GraphSchemaManager
from src.models.entities import Entity, ExtractionResult, Relationship

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


def _make_entity(idx: int = 1, entity_type: str = "Person") -> Entity:
    return Entity(
        id=f"entity--00000000-0000-0000-0000-{idx:012d}",
        type=entity_type,
        name=f"Entity {idx}",
        created=_NOW,
        modified=_NOW,
        confidence=0.8,
    )


def _make_relationship(src_id: str, tgt_id: str) -> Relationship:
    return Relationship(
        id="relationship--00000000-0000-0000-0000-000000000099",
        type="USES",
        source_ref=src_id,
        target_ref=tgt_id,
        created=_NOW,
        modified=_NOW,
    )


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Neo4j driver that vends an AsyncMock session."""
    driver = MagicMock()

    result_mock = AsyncMock()
    result_mock.single = AsyncMock(
        return_value={"entity_id": "entity--00000000-0000-0000-0000-000000000001"}
    )

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)

    # context-manager protocol
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    return driver


@pytest.fixture()
def persistence(mock_driver: MagicMock) -> GraphPersistenceService:
    return GraphPersistenceService(mock_driver)


# ---------------------------------------------------------------------------
# test_upsert_entity_new
# ---------------------------------------------------------------------------


async def test_upsert_entity_new(
    persistence: GraphPersistenceService,
    mock_driver: MagicMock,
) -> None:
    """upsert_entity should call MERGE with :Entity label."""
    entity = _make_entity(1)

    result_id = await persistence.upsert_entity(entity, tenant_id="tenant-A")

    mock_driver.session.assert_called()
    session = mock_driver.session.return_value.__aenter__.return_value
    assert session.run.called

    cypher_call: Any = session.run.call_args
    cypher: str = cypher_call.args[0]
    assert "MERGE" in cypher
    assert "Entity" in cypher
    assert result_id == "entity--00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# test_upsert_entity_update
# ---------------------------------------------------------------------------


async def test_upsert_entity_update(
    persistence: GraphPersistenceService,
    mock_driver: MagicMock,
) -> None:
    """Upserting the same entity twice should use ON MATCH SET."""
    entity = _make_entity(2)
    await persistence.upsert_entity(entity, tenant_id="tenant-A")
    await persistence.upsert_entity(entity, tenant_id="tenant-A")

    session = mock_driver.session.return_value.__aenter__.return_value
    assert session.run.call_count == 2
    cypher: str = session.run.call_args_list[0].args[0]
    assert "ON MATCH SET" in cypher


# ---------------------------------------------------------------------------
# test_upsert_relationship
# ---------------------------------------------------------------------------


async def test_upsert_relationship(
    persistence: GraphPersistenceService,
    mock_driver: MagicMock,
) -> None:
    """upsert_relationship should MERGE the correct edge type."""
    e1 = _make_entity(1)
    e2 = _make_entity(2)
    rel = _make_relationship(e1.id, e2.id)

    session = mock_driver.session.return_value.__aenter__.return_value
    session.run = AsyncMock(return_value=AsyncMock())

    await persistence.upsert_relationship(rel, tenant_id="tenant-A")

    assert session.run.called
    cypher: str = session.run.call_args.args[0]
    assert "MERGE" in cypher
    assert "USES" in cypher


# ---------------------------------------------------------------------------
# test_persist_extraction_transaction
# ---------------------------------------------------------------------------


async def test_persist_extraction_transaction() -> None:
    """All entities and relationships must be written in a single transaction."""
    e1 = _make_entity(1, "Organization")
    e2 = _make_entity(2, "Malware")
    rel = _make_relationship(e1.id, e2.id)

    extraction = ExtractionResult(
        source_event_id="evt-001",
        extraction_confidence=0.9,
        entities=[e1, e2],
        relationships=[rel],
    )

    tx_mock = AsyncMock()
    result_mock = AsyncMock()
    result_mock.single = AsyncMock(return_value={"entity_id": e1.id})
    tx_mock.run = AsyncMock(return_value=result_mock)
    tx_mock.commit = AsyncMock()
    tx_mock.__aenter__ = AsyncMock(return_value=tx_mock)
    tx_mock.__aexit__ = AsyncMock(return_value=False)

    session_mock = AsyncMock()
    session_mock.begin_transaction = AsyncMock(return_value=tx_mock)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    svc = GraphPersistenceService(driver)
    ids = await svc.persist_extraction(extraction, tenant_id="tenant-A")

    session_mock.begin_transaction.assert_called_once()
    # 2 entities + 1 relationship = 3 run() calls
    assert tx_mock.run.call_count == 3
    tx_mock.commit.assert_called_once()
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# test_persist_extraction_rollback
# ---------------------------------------------------------------------------


async def test_persist_extraction_rollback() -> None:
    """A write failure mid-transaction must propagate (no partial writes)."""
    e1 = _make_entity(1)
    e2 = _make_entity(2)

    extraction = ExtractionResult(
        source_event_id="evt-002",
        extraction_confidence=0.9,
        entities=[e1, e2],
    )

    tx_mock = AsyncMock()
    tx_mock.run = AsyncMock(side_effect=RuntimeError("neo4j write failure"))
    tx_mock.commit = AsyncMock()
    tx_mock.__aenter__ = AsyncMock(return_value=tx_mock)
    tx_mock.__aexit__ = AsyncMock(return_value=False)

    session_mock = AsyncMock()
    session_mock.begin_transaction = AsyncMock(return_value=tx_mock)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    svc = GraphPersistenceService(driver)

    with pytest.raises(RuntimeError, match="neo4j write failure"):
        await svc.persist_extraction(extraction, tenant_id="tenant-A")

    tx_mock.commit.assert_not_called()


# ---------------------------------------------------------------------------
# test_schema_initialize
# ---------------------------------------------------------------------------


async def test_schema_initialize() -> None:
    """GraphSchemaManager.initialize() must run exactly 5 Cypher statements."""
    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=AsyncMock())
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    schema = GraphSchemaManager(driver)
    await schema.initialize()

    # 2 constraint + 10 indexes = 12 calls
    assert session_mock.run.call_count == 12

    calls_text = " ".join(str(c) for c in session_mock.run.call_args_list)
    assert "CREATE CONSTRAINT" in calls_text
    assert "CREATE INDEX" in calls_text
    assert "Entity" in calls_text


# ---------------------------------------------------------------------------
# test_relationship_type_mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("input_type", "expected_edge"),
    [
        ("attributed-to", "ATTRIBUTED_TO"),
        ("targets", "TARGETS"),
        ("uses", "USES"),
        ("located-at", "LOCATED_AT"),
        ("related-to", "RELATED_TO"),
        ("dropped-by", "DROPPED_BY"),
        ("communicates-with", "COMMUNICATES_WITH"),
        ("has", "HAS"),
    ],
)
def test_relationship_type_mapping(input_type: str, expected_edge: str) -> None:
    assert _map_relationship_type(input_type) == expected_edge
