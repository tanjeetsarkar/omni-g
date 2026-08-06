"""Query profiler — classifies a search query and routes it to the appropriate
retrieval view (relational vs. temporal) with configurable depth limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# spaCy entity labels that indicate temporal queries
_TEMPORAL_LABELS = {"DATE", "TIME", "EVENT"}
# spaCy labels that indicate entity-centric (relational) queries
_ENTITY_LABELS = {"PERSON", "ORG", "GPE", "LOC", "FAC", "PRODUCT", "WORK_OF_ART", "NORP", "LAW"}


@dataclass
class QueryProfile:
    """Classification and routing metadata for a search query."""

    query: str
    route: Literal["relational", "local"] = "relational"
    d_max: int = 3
    keywords: list[str] = field(default_factory=list)
    temporal_cues: list[str] = field(default_factory=list)
    anchor_texts: list[str] = field(default_factory=list)


class QueryProfiler:
    """Classifies a free-text query into a routing profile.

    Loads spaCy ``en_core_web_trf`` on first call (lazy).
    """

    def __init__(self):
        self._nlp: Any = None

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            import spacy

            self._nlp = spacy.load("en_core_web_trf")
            logger.info("QueryProfiler spaCy model loaded")
        return self._nlp

    def profile(self, query: str) -> QueryProfile:
        """Produce a :class:`QueryProfile` for *query*."""
        nlp = self._get_nlp()
        doc = nlp(query)

        anchor_texts = [ent.text for ent in doc.ents if ent.label_ in _ENTITY_LABELS]
        temporal_cues = [ent.text for ent in doc.ents if ent.label_ in _TEMPORAL_LABELS]
        keywords = [
            tok.lemma_ for tok in doc if not tok.is_stop and tok.is_alpha and len(tok.text) > 2
        ]

        has_entities = bool(anchor_texts)
        has_temporal = bool(temporal_cues)

        if has_entities:
            route: Literal["relational", "local"] = "relational"
            d_max = 2 if has_temporal else 3
        else:
            route = "local"
            d_max = 2

        return QueryProfile(
            query=query,
            route=route,
            d_max=d_max,
            keywords=keywords,
            temporal_cues=temporal_cues,
            anchor_texts=anchor_texts,
        )
