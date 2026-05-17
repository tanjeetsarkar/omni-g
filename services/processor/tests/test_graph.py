from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.graph.persistence import GraphPersistenceService, _map_relationship_type
from src.graph.schema import GraphSchemaManager
from src.models.stix import (
    ExtractionResult,
    Malware,
    Relationship,
    ThreatActor,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


def _make_threat_actor(idx: int = 1) -> ThreatActor:
    return ThreatActor(
        id=f"threat-actor--00000000-0000-0000-0000-{idx:012d}",
        created=_NOW,
        modified=_NOW,
        name=f"Actor {idx}",
    )


def _make_malware(idx: int = 1) -> Malware:
    return Malware(
        id=f"malware--00000000-0000-0000-0000-{idx:012d}",
        created=_NOW,
        modified=_NOW,
        name=f"Malware {idx}",
        malware_types=["ransomware"],
    )


def _make_relationship(src_id: str, tgt_id: str) -> Relationship:
    return Relationship(
        id="relationship--00000000-0000-0000-0000-000000000099",
        created=_NOW,
        modified=_NOW,
        relationship_type="uses",
        source_ref=src_id,
        target_ref=tgt_id,
    )


def _make_mock_session() -> MagicMock:
    """Return a MagicMock that quacks like an AsyncSession."""
    session = MagicMock()
    result_mock = AsyncMock()
    result_mock.single = AsyncMock(
        return_value={
            "entity_id": "threat-actor--00000000-0000-0000-0000-000000000001"
        }
    )
    session.run = AsyncMock(return_value=result_mock)
    return session


@pytest.fixture()
def mock_driver() -> MagicMock:
    """Neo4j driver that vends an AsyncMock session."""
    driver = MagicMock()

    result_mock = AsyncMock()
    result_mock.single = AsyncMock(
        return_value={"entity_id": "threat-actor--00000000-0000-0000-0000-000000000001"}
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
    """upsert_entity should call MERGE with the correct label and properties."""
    actor = _make_threat_actor(1)

    result_id = await persistence.upsert_entity(actor, tenant_id="tenant-A")

    # Verify the session was used
    mock_driver.session.assert_called()
    session = mock_driver.session.return_value.__aenter__.return_value
    assert session.run.called

    # Check the Cypher contains MERGE and STIXEntity label
    cypher_call: Any = session.run.call_args
    cypher: str = cypher_call.args[0]
    assert "MERGE" in cypher
    assert "STIXEntity" in cypher
    assert "ThreatActor" in cypher
    assert result_id == "threat-actor--00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# test_upsert_entity_update
# ---------------------------------------------------------------------------


async def test_upsert_entity_update(
    persistence: GraphPersistenceService,
    mock_driver: MagicMock,
) -> None:
    """Upserting the same entity twice should use ON MATCH SET."""
    actor = _make_threat_actor(2)
    await persistence.upsert_entity(actor, tenant_id="tenant-A")
    await persistence.upsert_entity(actor, tenant_id="tenant-A")

    session = mock_driver.session.return_value.__aenter__.return_value
    # run called twice (once per upsert)
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
    actor = _make_threat_actor(1)
    malware = _make_malware(1)
    rel = _make_relationship(actor.id, malware.id)

    # make run return an AsyncMock result (not checked for relationships)
    session = mock_driver.session.return_value.__aenter__.return_value
    session.run = AsyncMock(return_value=AsyncMock())

    await persistence.upsert_relationship(rel, tenant_id="tenant-A")

    assert session.run.called
    cypher: str = session.run.call_args.args[0]
    assert "MERGE" in cypher
    assert "USES" in cypher  # "uses" → USES


# ---------------------------------------------------------------------------
# test_persist_extraction_transaction
# ---------------------------------------------------------------------------


async def test_persist_extraction_transaction() -> None:
    """All entities and relationships must be written in a single transaction."""
    actor = _make_threat_actor(1)
    malware = _make_malware(1)
    rel = _make_relationship(actor.id, malware.id)

    extraction = ExtractionResult(
        source_event_id="evt-001",
        extraction_confidence=0.9,
        threat_actors=[actor],
        malware=[malware],
        relationships=[rel],
    )

    # Build a driver that yields a transaction mock
    tx_mock = AsyncMock()
    result_mock = AsyncMock()
    result_mock.single = AsyncMock(
        return_value={"entity_id": actor.id}
    )
    tx_mock.run = AsyncMock(return_value=result_mock)
    tx_mock.commit = AsyncMock()

    session_mock = AsyncMock()
    session_mock.begin_transaction = AsyncMock(return_value=tx_mock)
    # context-manager for the transaction itself
    tx_mock.__aenter__ = AsyncMock(return_value=tx_mock)
    tx_mock.__aexit__ = AsyncMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    svc = GraphPersistenceService(driver)
    ids = await svc.persist_extraction(extraction, tenant_id="tenant-A")

    # transaction opened once
    session_mock.begin_transaction.assert_called_once()
    # 2 entities + 1 relationship = 3 run() calls
    assert tx_mock.run.call_count == 3
    # committed
    tx_mock.commit.assert_called_once()
    assert len(ids) == 2  # 2 SDOs


# ---------------------------------------------------------------------------
# test_persist_extraction_rollback
# ---------------------------------------------------------------------------


async def test_persist_extraction_rollback() -> None:
    """A write failure mid-transaction must propagate (no partial writes)."""
    actor = _make_threat_actor(1)
    malware = _make_malware(1)

    extraction = ExtractionResult(
        source_event_id="evt-002",
        extraction_confidence=0.9,
        threat_actors=[actor],
        malware=[malware],
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

    # commit must NOT have been called
    tx_mock.commit.assert_not_called()


# ---------------------------------------------------------------------------
# test_schema_initialize
# ---------------------------------------------------------------------------


async def test_schema_initialize() -> None:
    """GraphSchemaManager.initialize() must run constraint + index Cypher for each label."""
    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=AsyncMock())
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session_mock)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

    schema = GraphSchemaManager(driver)
    await schema.initialize()

    # 7 labels × 4 statements (constraint + 3 indexes) = 28 calls
    assert session_mock.run.call_count == 28

    calls_text = " ".join(str(c) for c in session_mock.run.call_args_list)
    assert "CREATE CONSTRAINT" in calls_text
    assert "CREATE INDEX" in calls_text
    assert "ThreatActor" in calls_text
    assert "Malware" in calls_text


# ---------------------------------------------------------------------------
# test_relationship_type_mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stix_type", "expected_edge"),
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
def test_relationship_type_mapping(stix_type: str, expected_edge: str) -> None:
    assert _map_relationship_type(stix_type) == expected_edge
