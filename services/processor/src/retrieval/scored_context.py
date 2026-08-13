"""Shared ScoredContext dataclass used by all retrieval components."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoredContext:
    """A retrieved ContextUnit with an activation score."""

    context_id: str
    score: float
    text: str
    entity_ids: list[str] = field(default_factory=list)
    source_event_id: str | None = None
    # V4 Track 2: human-readable provenance threaded from ContextUnit nodes
    # through retrieval → fusion → calibration → search response so the UI
    # can render source tags without extra Neo4j round-trips.
    source_name: str | None = None
    source_url: str | None = None
    plugin_name: str | None = None
