"""Generic entity model for the Omni-G Knowledge Graph.

Replaces the STIX 2.1 fixed-ontology model with an open-ended, LLM-determined
entity type system.  The LLM freely assigns entity types (Person, Organization,
Event, Location, Topic, Concept, …) rather than choosing from a fixed enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    """Text excerpt from the source event that explicitly mentions an entity.

    The pipeline grounding gate uses this to verify that extracted entities
    are directly supported by raw feed content, preventing LLM hallucination
    from entering the Knowledge Graph.
    """

    text: str  # Verbatim excerpt from the source text that mentions the entity
    start: int = 0  # Best-effort character offset in source text (start)
    end: int = 0  # Best-effort character offset in source text (end)


class Entity(BaseModel):
    """A generic knowledge-graph entity with an open-ended type.

    ``type`` is a free-form string determined by the LLM from context
    (e.g. "Person", "Organization", "Event", "Location", "Topic", "Concept").
    """

    id: str  # "entity--{uuid4}"
    type: str  # Open-ended: "Person", "Organization", "Event", etc.
    name: str
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tenant_id: str = ""  # set by pipeline; empty at extraction time
    source_id: str | None = None  # plugin HTTP source URL
    source_spans: list[EvidenceSpan] = Field(default_factory=list)  # Evidence from raw feed
    created: datetime
    modified: datetime


class Relationship(BaseModel):
    """A directed relationship between two Entity nodes.

    ``type`` is a free-form string, typically UPPER_SNAKE_CASE
    (e.g. "KNOWS", "LOCATED_AT", "PARTICIPATED_IN", "ACQUIRED").
    """

    id: str  # "relationship--{uuid4}"
    type: str  # Open-ended: "KNOWS", "LOCATED_AT", "PARTICIPATED_IN", etc.
    source_ref: str  # entity id
    target_ref: str  # entity id
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tenant_id: str = ""  # set by pipeline; empty at extraction time
    created: datetime
    modified: datetime


class ExtractionResult(BaseModel):
    """Container for all entities extracted from a single raw event."""

    source_event_id: str
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    plugin_id: str | None = None
    plugin_version: str | None = None
