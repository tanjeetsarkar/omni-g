from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

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
    created_by_ref: str | None = None


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


class Identity(STIXObject):
    type: STIXType = STIXType.IDENTITY
    name: str
    identity_class: str
    sectors: list[str] = Field(default_factory=list)


class AttackPattern(STIXObject):
    type: STIXType = STIXType.ATTACK_PATTERN
    name: str
    description: str | None = None
    kill_chain_phases: list[dict[str, Any]] = Field(default_factory=list)


class Campaign(STIXObject):
    type: STIXType = STIXType.CAMPAIGN
    name: str
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class Indicator(STIXObject):
    type: STIXType = STIXType.INDICATOR
    name: str
    indicator_types: list[str] = Field(default_factory=list)
    pattern: str
    pattern_type: str = "stix"
    valid_from: datetime


class Location(STIXObject):
    type: STIXType = STIXType.LOCATION
    name: str | None = None
    country: str | None = None
    region: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class Relationship(BaseModel):
    """STIX 2.1 Relationship Object (SRO) — not an SDO, separate model."""

    type: Literal["relationship"] = "relationship"
    id: str = Field(pattern=r"^[a-z-]+--[0-9a-f-]{36}$")
    spec_version: str = "2.1"
    created: datetime
    modified: datetime
    relationship_type: str
    source_ref: str
    target_ref: str
    description: str | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    created_by_ref: str | None = None


class STIXBundle(BaseModel):
    """STIX 2.1 Bundle container."""

    type: Literal["bundle"] = "bundle"
    id: str = Field(pattern=r"^bundle--[0-9a-f-]{36}$")
    objects: list[Any] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Container for all entities extracted from a single raw event."""

    source_event_id: str
    threat_actors: list[ThreatActor] = Field(default_factory=list)
    malware: list[Malware] = Field(default_factory=list)
    identities: list[Identity] = Field(default_factory=list)
    attack_patterns: list[AttackPattern] = Field(default_factory=list)
    campaigns: list[Campaign] = Field(default_factory=list)
    indicators: list[Indicator] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    raw_entities: list[dict[str, Any]] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    plugin_id: str | None = None
    plugin_version: str | None = None

    def all_entities(self) -> list[STIXObject]:
        """Return every SDO in this result as a flat list (excludes SROs)."""
        return (
            list(self.threat_actors)
            + list(self.malware)
            + list(self.identities)
            + list(self.attack_patterns)
            + list(self.campaigns)
            + list(self.indicators)
            + list(self.locations)
        )
