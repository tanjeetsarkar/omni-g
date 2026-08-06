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
