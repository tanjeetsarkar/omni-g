"""Generic entity model for the Omni-G Knowledge Graph (V3 Zero-Mem).

V3 removes the V2 intelligence-cycle models (KIQ/Evidence/Assessment/Hypothesis)
in favour of a ContextUnit-first graph schema backed by NER-based extraction.
LLM calls are reserved solely for final synthesis in Delivery.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    """Verbatim text excerpt from the source event that mentions an entity."""

    text: str
    start: int = 0
    end: int = 0


class Entity(BaseModel):
    """A generic knowledge-graph entity with an open-ended type.

    ``type`` is a free-form string produced by NER models from context
    (e.g. "PERSON", "ORG", "GPE", "LOCATION", "CONCEPT").
    """

    id: str  # "entity--{uuid4}"
    type: str
    name: str
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tenant_id: str = ""  # set by pipeline; empty at extraction time
    source_id: str | None = None
    source_spans: list[EvidenceSpan] = Field(default_factory=list)
    created: datetime
    modified: datetime


class Relationship(BaseModel):
    """A directed relationship between two Entity nodes."""

    id: str  # "relationship--{uuid4}"
    type: str  # UPPER_SNAKE_CASE: "KNOWS", "LOCATED_AT", "CO_OCCURRED_WITH", etc.
    source_ref: str
    target_ref: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tenant_id: str = ""
    created: datetime
    modified: datetime


class ContextUnit(BaseModel):
    """A raw context chunk (document fragment) persisted as a graph node.

    ContextUnits are the primary nodes in the V3 Zero-Mem graph.
    Each ingested raw event produces one ContextUnit.  Entity nodes are
    detected from the text and linked via CO_OCCURRED_IN edges.
    """

    id: str  # "context--{uuid4}"
    text: str
    source_id: str | None = None
    tenant_id: str
    session_id: str | None = None
    episode_id: str | None = None
    window_id: str | None = None
    created: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Container for all entities extracted from a single raw event."""

    source_event_id: str
    context_unit_id: str = ""  # ID of the ContextUnit created from this event
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    plugin_id: str | None = None
    plugin_version: str | None = None
    # Normalised co-occurrence weight per entity: w(d,e) = c(e,d) / Σ_e' c(e',d)
    entity_context_weights: dict[str, float] = Field(default_factory=dict)
