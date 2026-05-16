from datetime import UTC

import pytest

from src.models.stix import ExtractionResult, Malware, STIXType, ThreatActor


def test_threat_actor_type_is_correct() -> None:
    assert ThreatActor.__fields__["type"].default == STIXType.THREAT_ACTOR  # type: ignore[attr-defined]


def test_malware_type_is_correct() -> None:
    assert Malware.__fields__["type"].default == STIXType.MALWARE  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "confidence,valid",
    [
        (0, True),
        (50, True),
        (100, True),
        (-1, False),
        (101, False),
    ],
)
def test_stix_confidence_validation(confidence: int, valid: bool) -> None:
    from datetime import datetime

    from pydantic import ValidationError

    now = datetime.now(tz=UTC)
    data = {
        "type": "threat-actor",
        "id": "threat-actor--12345678-1234-5678-1234-567812345678",
        "created": now,
        "modified": now,
        "name": "APT1",
        "confidence": confidence,
    }
    if valid:
        actor = ThreatActor(**data)
        assert actor.confidence == confidence
    else:
        with pytest.raises(ValidationError):
            ThreatActor(**data)


def test_extraction_result_defaults_are_empty() -> None:
    result = ExtractionResult(source_event_id="test-123", extraction_confidence=0.0)
    assert result.threat_actors == []
    assert result.malware == []
    assert result.raw_entities == []
