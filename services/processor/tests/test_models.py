"""Tests for the generic entity model (entities.py)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.entities import Entity, ExtractionResult, Relationship

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def test_entity_type_any_string() -> None:
    for t in ("Person", "Organization", "Event", "Location", "Topic", "Concept", "Malware"):
        entity = _make_entity(type=t)
        assert entity.type == t


def test_entity_confidence_defaults_to_half() -> None:
    entity = _make_entity()
    assert entity.confidence == 0.5


@pytest.mark.parametrize(
    "confidence,valid",
    [
        (0.0, True),
        (0.5, True),
        (1.0, True),
        (-0.1, False),
        (1.1, False),
    ],
)
def test_entity_confidence_validation(confidence: float, valid: bool) -> None:
    if valid:
        e = _make_entity(confidence=confidence)
        assert e.confidence == confidence
    else:
        with pytest.raises(ValidationError):
            _make_entity(confidence=confidence)


def test_entity_tenant_id_defaults_to_empty_string() -> None:
    entity = _make_entity()
    assert entity.tenant_id == ""


def test_entity_tenant_id_set_by_caller() -> None:
    entity = _make_entity(tenant_id="acme")
    assert entity.tenant_id == "acme"


def test_entity_properties_default_empty() -> None:
    entity = _make_entity()
    assert entity.properties == {}


def test_entity_properties_stores_arbitrary_data() -> None:
    entity = _make_entity(properties={"aliases": ["Bob"], "sectors": ["tech"]})
    assert entity.properties["aliases"] == ["Bob"]


def test_entity_description_optional() -> None:
    entity = _make_entity()
    assert entity.description is None
    entity2 = _make_entity(description="A person of interest")
    assert entity2.description == "A person of interest"


def test_entity_source_id_optional() -> None:
    entity = _make_entity()
    assert entity.source_id is None


# ---------------------------------------------------------------------------
# Relationship tests
# ---------------------------------------------------------------------------


def test_relationship_type_is_open_ended() -> None:
    rel = _make_relationship(type="ATTRIBUTED_TO")
    assert rel.type == "ATTRIBUTED_TO"


def test_relationship_confidence_defaults_to_half() -> None:
    rel = _make_relationship()
    assert rel.confidence == 0.5


@pytest.mark.parametrize("conf,valid", [(0.0, True), (1.0, True), (-0.1, False), (1.1, False)])
def test_relationship_confidence_validation(conf: float, valid: bool) -> None:
    if valid:
        rel = _make_relationship(confidence=conf)
        assert rel.confidence == conf
    else:
        with pytest.raises(ValidationError):
            _make_relationship(confidence=conf)


def test_relationship_tenant_id_defaults_empty() -> None:
    rel = _make_relationship()
    assert rel.tenant_id == ""


# ---------------------------------------------------------------------------
# ExtractionResult tests
# ---------------------------------------------------------------------------


def test_extraction_result_defaults_are_empty() -> None:
    result = ExtractionResult(source_event_id="test-123")
    assert result.entities == []
    assert result.relationships == []


def test_extraction_result_confidence_defaults_to_zero() -> None:
    result = ExtractionResult(source_event_id="test-123")
    assert result.extraction_confidence == 0.0


def test_extraction_result_holds_entities_and_relationships() -> None:
    entity = _make_entity()
    rel = _make_relationship()
    result = ExtractionResult(
        source_event_id="ev-1",
        entities=[entity],
        relationships=[rel],
        extraction_confidence=0.9,
    )
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"
    assert len(result.relationships) == 1
    assert result.relationships[0].type == "KNOWS"


def test_extraction_result_plugin_fields_optional() -> None:
    result = ExtractionResult(source_event_id="ev-1")
    assert result.plugin_id is None
    assert result.plugin_version is None


def test_extraction_result_kiq_id_defaults_to_none() -> None:
    result = ExtractionResult(source_event_id="ev-kiq")
    assert result.kiq_id is None


def test_extraction_result_kiq_id_accepted() -> None:
    result = ExtractionResult(source_event_id="ev-kiq", kiq_id="kiq--abc123")
    assert result.kiq_id == "kiq--abc123"
