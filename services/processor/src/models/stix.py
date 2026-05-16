from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class STIXType(StrEnum):
    THREAT_ACTOR = "threat-actor"
    IDENTITY = "identity"
    MALWARE = "malware"
    ATTACK_PATTERN = "attack-pattern"
    CAMPAIGN = "campaign"
    INDICATOR = "indicator"
    RELATIONSHIP = "relationship"
    LOCATION = "location"


class STIXObject(BaseModel):
    """Base model for all STIX 2.1 Domain Objects (SDOs)."""

    type: STIXType
    id: str = Field(pattern=r"^[a-z-]+--[0-9a-f-]{36}$")
    spec_version: str = "2.1"
    created: datetime
    modified: datetime
    confidence: int | None = Field(default=None, ge=0, le=100)
    custom_properties: dict[str, Any] = Field(default_factory=dict)


class ThreatActor(STIXObject):
    type: STIXType = STIXType.THREAT_ACTOR
    name: str
    aliases: list[str] = Field(default_factory=list)
    threat_actor_types: list[str] = Field(default_factory=list)
    description: str | None = None


class Malware(STIXObject):
    type: STIXType = STIXType.MALWARE
    name: str
    malware_types: list[str] = Field(default_factory=list)
    is_family: bool = False
    description: str | None = None


class ExtractionResult(BaseModel):
    """Container for all entities extracted from a single raw event."""

    source_event_id: str
    threat_actors: list[ThreatActor] = Field(default_factory=list)
    malware: list[Malware] = Field(default_factory=list)
    raw_entities: list[dict[str, Any]] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
