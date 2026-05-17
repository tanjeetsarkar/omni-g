from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from ..models.stix import STIXObject


class ResolutionDecision(StrEnum):
    """Outcome of an entity resolution attempt."""

    AUTO_MERGE = "auto_merge"
    AMBIGUOUS = "ambiguous"
    NEW_ENTITY = "new_entity"


class CandidateMatch(BaseModel):
    """A candidate entity that may be the same as an incoming entity."""

    entity_id: str
    score: float  # 0.0–1.0
    match_type: str  # "vector" | "structural"


class ResolutionResult(BaseModel):
    """Full result of resolving a single STIX entity."""

    decision: ResolutionDecision
    matched_entity_id: str | None  # None when decision is NEW_ENTITY
    confidence_score: float
    entity: STIXObject
