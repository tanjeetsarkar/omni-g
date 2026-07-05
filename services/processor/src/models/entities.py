"""Generic entity model for the Omni-G Knowledge Graph.

Replaces the STIX 2.1 fixed-ontology model with an open-ended, LLM-determined
entity type system.  The LLM freely assigns entity types (Person, Organization,
Event, Location, Topic, Concept, …) rather than choosing from a fixed enum.

V2 additions: SourceClassification, ReliabilityRating, CredibilityRating enums
and CollectedEvidence model for intelligence-cycle evidence tracking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
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
    # kiq_id carries the Key Intelligence Question reference from the originating
    # RawEvent. None means the event was untasked (general collection).
    kiq_id: str | None = None
    # V2: collected evidence objects created after grounding validation.
    collected_evidence: list[CollectedEvidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# V2 Evidence scoring models (Step 6)
# ---------------------------------------------------------------------------


class SourceClassification(str, Enum):
    """Source discipline classification (Admiralty-style)."""

    HUMAN_INTELLIGENCE = "HUMINT"
    SIGNALS_INTELLIGENCE = "SIGINT"
    IMAGERY_INTELLIGENCE = "IMINT"
    OPEN_SOURCE_INTELLIGENCE = "OSINT"
    MEASUREMENT_INTELLIGENCE = "MASINT"
    TECHNICAL_INTELLIGENCE = "TECHINT"
    UNKNOWN = "UNKNOWN"


class ReliabilityRating(str, Enum):
    """Source reliability (A–F Admiralty rating).

    A — always reliable, B — usually reliable, C — fairly reliable,
    D — unreliable, E — always unreliable, F — reliability unknown.
    """

    ALWAYS_RELIABLE = "A"
    USUALLY_RELIABLE = "B"
    FAIRLY_RELIABLE = "C"
    UNRELIABLE = "D"
    ALWAYS_UNRELIABLE = "E"
    UNKNOWN = "F"


class CredibilityRating(str, Enum):
    """Information credibility (1–6 Admiralty rating).

    1 — confirmed, 2 — probably true, 3 — possibly true,
    4 — doubtful, 5 — improbable, 6 — cannot be judged.
    """

    CONFIRMED = "1"
    PROBABLY_TRUE = "2"
    POSSIBLY_TRUE = "3"
    DOUBTFUL = "4"
    IMPROBABLE = "5"
    CANNOT_BE_JUDGED = "6"


class CollectedEvidence(BaseModel):
    """Extracted and scored evidence from a raw feed.

    Wraps an extracted Entity or Relationship with KIQ tasking context,
    Admiralty-style source classification, and reliability/credibility scoring.
    Created by the Processor after grounding validation; published as
    ``evidence.created`` Kafka events for downstream Delivery consumption.
    """

    # Identity
    id: str  # "evidence--{uuid4}"
    tenant_id: str  # Multi-tenant isolation (required)

    # Provenance
    kiq_id: str | None = None  # Which KIQ motivated collection; None = untasked
    source_event_id: str  # Reference to the originating RawEvent id
    plugin_id: str | None = None  # MCP plugin or source that provided this
    plugin_version: str | None = None

    # The claim — exactly one of entity_id or relationship_id should be set
    entity_id: str | None = None
    relationship_id: str | None = None
    assertion: str  # Human-readable: "Person 'Alice' extracted from source"

    # Sourcing details
    source_text: str = ""  # Verbatim excerpt from source (best-effort)
    source_url: str | None = None  # URL of originating article/post
    source_timestamp: datetime  # When the source was published/captured

    # Source classification and reliability (Admiralty scale)
    source_class: SourceClassification = SourceClassification.UNKNOWN
    source_reliability: ReliabilityRating = ReliabilityRating.UNKNOWN
    information_credibility: CredibilityRating = CredibilityRating.CANNOT_BE_JUDGED

    # Confidence in extraction quality (0.0–1.0)
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # Application state
    status: str = "NEW"  # NEW, CONFIRMED, DISPUTED, SUPERSEDED
    tags: list[str] = Field(default_factory=list)

    created: datetime
    modified: datetime
