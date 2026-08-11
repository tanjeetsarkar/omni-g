"""V4 API response models for the graph query endpoints.

These models give the Delivery layer a structured, human-readable payload:
every node carries provenance (source name/URL/plugin) and a raw context
snippet with character offsets, so the UI can render source tags and
evidence drawers without exposing database IDs or plugin URLs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NodeProvenance(BaseModel):
    """Human-readable source provenance attached to every rendered node."""

    source_name: str
    source_url: str | None = None
    ingested_at: str
    mcp_plugin_name: str | None = None


class RawContextSnippet(BaseModel):
    """Verbatim source text excerpt with character offsets for the drawer."""

    snippet_text: str
    char_offset_start: int = 0
    char_offset_end: int = 0
    document_id: str


class CustomNodeResponse(BaseModel):
    """A single graph node formatted for the ECharts rich-text card renderer.

    ``sub_entity_count`` is the degree of the entity within the returned
    subgraph (number of incident edges), surfaced as the "+N links" badge.
    """

    id: str
    entity_name: str
    entity_type: str
    sub_entity_count: int = 0
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    source: NodeProvenance
    raw_context: RawContextSnippet | None = None


class GraphQueryResponse(BaseModel):
    """Top-level response for /search and /query/expand.

    Carries the structured ``nodes`` array alongside the legacy
    ``entities`` / ``relationships`` / ``context_units`` arrays so existing
    Delivery consumers can migrate incrementally.
    """

    nodes: list[CustomNodeResponse] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    context_units: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    # Zero-Mem verification: graph expansion must not consume LLM memory
    # tokens. Surfaced as 0 so the UI can assert the invariant.
    total_tokens_consumed: int = 0
