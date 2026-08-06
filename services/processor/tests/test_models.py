"""Tests for the V3 generic entity model (entities.py)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.entities import ContextUnit, Entity, ExtractionResult, Relationship


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_entity(**overrides) -> Entity:
    defaults = dict(
        id="entity--12345678-1234-5678-1234-567812345678",
        type="Person",
        name="Alice",
        created=_now(),
        modified=_now(),
    )
    defaults.update(overrides)
    return Entity.model_validate(defaults)


def _make_relationship(**overrides) -> Relationship:
    defaults = dict(
        id="relationship--12345678-1234-5678-1234-567812345678",
        type="KNOWS",
        source_ref="entity--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        target_ref="entity--bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        created=_now(),
        modified=_now(),
    )
    defaults.update(overrides)
    return Relationship.model_validate(defaults)


# ---------------------------------------------------------------------------
# Entity tests
# ---------------------------------------------------------------------------


def test_entity_type_is_open_ended_string() -> None:
    entity = _make_entity(type="ThreatActor")
    assert entity.type == "ThreatActor"


def test_entity_default_confidence() -> None:
    entity = _make_entity()
    assert entity.confidence == 0.5


def test_entity_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        _make_entity(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_entity(confidence=-0.1)


def test_entity_optional_fields() -> None:
    entity = _make_entity()
    assert entity.description is None
    assert entity.source_id is None
    assert entity.source_spans == []
    assert entity.tenant_id == ""


def test_entity_with_properties() -> None:
    entity = _make_entity(properties={"country": "US", "aliases": ["Alice A"]})
    assert entity.properties["country"] == "US"


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


def test_relationship_type_open_ended() -> None:
    rel = _make_relationship(type="PARTICIPATED_IN")
    assert rel.type == "PARTICIPATED_IN"


def test_relationship_default_confidence() -> None:
    rel = _make_relationship()
    assert rel.confidence == 0.5


# ---------------------------------------------------------------------------
# ContextUnit tests
# ---------------------------------------------------------------------------


def test_context_unit_fields() -> None:
    unit = ContextUnit(
        id="context--abc123",
        text="Alice was seen at the conference.",
        tenant_id="tenant-a",
        created=_now(),
    )
    assert unit.id == "context--abc123"
    assert unit.tenant_id == "tenant-a"
    assert unit.session_id is None
    assert unit.episode_id is None
    assert unit.metadata == {}


def test_context_unit_with_hierarchy() -> None:
    unit = ContextUnit(
        id="context--xyz",
        text="Test text.",
        tenant_id="tenant-a",
        session_id="sess-1",
        episode_id="ep-1",
        window_id="win-5",
        created=_now(),
    )
    assert unit.session_id == "sess-1"
    assert unit.episode_id == "ep-1"
    assert unit.window_id == "win-5"


# ---------------------------------------------------------------------------
# ExtractionResult tests
# ---------------------------------------------------------------------------


def test_extraction_result_defaults() -> None:
    result = ExtractionResult(source_event_id="evt-1")
    assert result.entities == []
    assert result.relationships == []
    assert result.extraction_confidence == 0.0
    assert result.context_unit_id == ""
    assert result.entity_context_weights == {}


def test_extraction_result_with_entities() -> None:
    e = _make_entity()
    result = ExtractionResult(
        source_event_id="evt-2",
        context_unit_id="context--abc",
        entities=[e],
        entity_context_weights={e.id: 1.0},
        extraction_confidence=0.75,
    )
    assert len(result.entities) == 1
    assert result.entity_context_weights[e.id] == 1.0


def test_extraction_result_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        ExtractionResult(source_event_id="evt-3", extraction_confidence=1.5)
