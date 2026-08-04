"""Tests for the generic entity model (entities.py)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.entities import (
    CollectedEvidence,
    CredibilityRating,
    Entity,
    ExtractionResult,
    Relationship,
    ReliabilityRating,
    SourceClassification,
)

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


def test_extraction_result_collected_evidence_defaults_empty() -> None:
    result = ExtractionResult(source_event_id="ev-1")
    assert result.collected_evidence == []


# ---------------------------------------------------------------------------
# SourceClassification tests
# ---------------------------------------------------------------------------


def test_source_classification_values() -> None:
    assert SourceClassification.OPEN_SOURCE_INTELLIGENCE == "OSINT"
    assert SourceClassification.HUMAN_INTELLIGENCE == "HUMINT"
    assert SourceClassification.UNKNOWN == "UNKNOWN"


def test_source_classification_is_str_enum() -> None:
    assert isinstance(SourceClassification.OPEN_SOURCE_INTELLIGENCE, str)


# ---------------------------------------------------------------------------
# ReliabilityRating tests
# ---------------------------------------------------------------------------


def test_reliability_rating_values() -> None:
    assert ReliabilityRating.ALWAYS_RELIABLE == "A"
    assert ReliabilityRating.UNKNOWN == "F"


def test_reliability_rating_all_grades() -> None:
    grades = [r.value for r in ReliabilityRating]
    assert set(grades) == {"A", "B", "C", "D", "E", "F"}


# ---------------------------------------------------------------------------
# CredibilityRating tests
# ---------------------------------------------------------------------------


def test_credibility_rating_values() -> None:
    assert CredibilityRating.CONFIRMED == "1"
    assert CredibilityRating.CANNOT_BE_JUDGED == "6"


def test_credibility_rating_all_grades() -> None:
    grades = [r.value for r in CredibilityRating]
    assert set(grades) == {"1", "2", "3", "4", "5", "6"}


# ---------------------------------------------------------------------------
# CollectedEvidence tests
# ---------------------------------------------------------------------------


def _make_evidence(**overrides) -> CollectedEvidence:
    defaults = dict(
        id="evidence--12345678-1234-5678-1234-567812345678",
        tenant_id="acme",
        source_event_id="evt-001",
        entity_id="entity--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        assertion="Person 'Alice' extracted from source",
        source_timestamp=_now(),
        created=_now(),
        modified=_now(),
    )
    defaults.update(overrides)
    return CollectedEvidence.model_validate(defaults)


def test_collected_evidence_defaults() -> None:
    ev = _make_evidence()
    assert ev.kiq_id is None
    assert ev.source_class == SourceClassification.UNKNOWN
    assert ev.source_reliability == ReliabilityRating.UNKNOWN
    assert ev.information_credibility == CredibilityRating.CANNOT_BE_JUDGED
    assert ev.extraction_confidence == 0.5
    assert ev.status == "NEW"
    assert ev.tags == []


def test_collected_evidence_with_kiq() -> None:
    ev = _make_evidence(kiq_id="kiq--abc123")
    assert ev.kiq_id == "kiq--abc123"


def test_collected_evidence_source_class_osint() -> None:
    ev = _make_evidence(source_class="OSINT")
    assert ev.source_class == SourceClassification.OPEN_SOURCE_INTELLIGENCE


def test_collected_evidence_reliability_rating() -> None:
    ev = _make_evidence(source_reliability="B")
    assert ev.source_reliability == ReliabilityRating.USUALLY_RELIABLE


def test_collected_evidence_credibility_rating() -> None:
    ev = _make_evidence(information_credibility="2")
    assert ev.information_credibility == CredibilityRating.PROBABLY_TRUE


def test_collected_evidence_extraction_confidence_bounds() -> None:
    ev = _make_evidence(extraction_confidence=0.9)
    assert ev.extraction_confidence == 0.9
    with pytest.raises(ValidationError):
        _make_evidence(extraction_confidence=1.5)
    with pytest.raises(ValidationError):
        _make_evidence(extraction_confidence=-0.1)


def test_collected_evidence_relationship_id() -> None:
    ev = _make_evidence(
        entity_id=None,
        relationship_id="relationship--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        assertion="Relationship 'KNOWS' extracted",
    )
    assert ev.entity_id is None
    assert ev.relationship_id == "relationship--aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_collected_evidence_tenant_id_required() -> None:
    with pytest.raises(ValidationError):
        CollectedEvidence.model_validate(
            dict(
                id="evidence--12345678-1234-5678-1234-567812345678",
                source_event_id="evt-001",
                assertion="test",
                source_timestamp=_now(),
                created=_now(),
                modified=_now(),
                # tenant_id intentionally omitted
            )
        )


def test_extraction_result_stores_collected_evidence() -> None:
    ev = _make_evidence()
    result = ExtractionResult(
        source_event_id="evt-001",
        collected_evidence=[ev],
    )
    assert len(result.collected_evidence) == 1
    assert result.collected_evidence[0].assertion == "Person 'Alice' extracted from source"
