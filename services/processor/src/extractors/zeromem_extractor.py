"""Zero-Token NER-based entity extractor (Phase 4).

Replaces the LLM extraction stage with spaCy + GLiNER pipeline.
Zero LLM calls — all entity detection is done by local NER models.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..models.entities import Entity, EvidenceSpan, ExtractionResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# GLiNER generic entity labels for domain-agnostic extraction
_GLINER_LABELS = [
    "person",
    "organization",
    "location",
    "concept",
    "event",
    "product",
    "facility",
    "topic",
]


class ZeroMemExtractor:
    """NER-based entity extractor using spaCy (en_core_web_trf) + GLiNER.

    Loaded once at runtime initialisation.  Both models are CPU-safe and run
    synchronously — the blocking call is acceptable because Celery workers
    run in separate processes and the extractor is not on the asyncio event loop.
    """

    def __init__(self) -> None:
        self._nlp: Any = None
        self._gliner: Any = None

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            import spacy

            self._nlp = spacy.load("en_core_web_trf")
        return self._nlp

    def _get_gliner(self) -> Any:
        if self._gliner is None:
            from gliner import GLiNER  # type: ignore[import-untyped]

            self._gliner = GLiNER.from_pretrained("urchade/gliner_small-v2.1")
        return self._gliner

    def extract(self, text: str, context_id: str, tenant_id: str) -> ExtractionResult:
        """Extract entities from *text* using spaCy + GLiNER.

        Returns an ExtractionResult with:
        - entities: merged list from spaCy NER + GLiNER
        - entity_context_weights: normalised co-occurrence weight per entity
          w(d,e) = c(e,d) / Σ_e' c(e',d)
        - extraction_confidence: proportional to number of entities found
        """
        if not text.strip():
            return ExtractionResult(
                source_event_id="",
                context_unit_id=context_id,
                entities=[],
                relationships=[],
                extraction_confidence=0.0,
            )

        now = datetime.now(UTC)
        entities: list[Entity] = []
        entity_counts: dict[str, int] = {}

        # ── spaCy NER ────────────────────────────────────────────────────
        nlp = self._get_nlp()
        doc = nlp(text)
        for ent in doc.ents:
            entity_id = f"entity--{uuid4()}"
            entities.append(
                Entity(
                    id=entity_id,
                    type=ent.label_,
                    name=ent.text.strip(),
                    confidence=0.75,
                    tenant_id=tenant_id,
                    source_spans=[
                        EvidenceSpan(text=ent.text, start=ent.start_char, end=ent.end_char)
                    ],
                    created=now,
                    modified=now,
                )
            )
            entity_counts[entity_id] = 1

        # ── GLiNER (generic types spaCy may miss) ─────────────────────────
        try:
            gliner = self._get_gliner()
            gliner_results = gliner.predict_entities(text, _GLINER_LABELS, threshold=0.5)
            for result in gliner_results:
                entity_id = f"entity--{uuid4()}"
                entities.append(
                    Entity(
                        id=entity_id,
                        type=result["label"].upper(),
                        name=result["text"].strip(),
                        confidence=min(float(result.get("score", 0.6)), 1.0),
                        tenant_id=tenant_id,
                        source_spans=[
                            EvidenceSpan(
                                text=result["text"],
                                start=result.get("start", 0),
                                end=result.get("end", 0),
                            )
                        ],
                        created=now,
                        modified=now,
                    )
                )
                entity_counts[entity_id] = 1
        except Exception:
            logger.exception("gliner_extraction_failed", extra={"context_id": context_id})

        # ── Co-occurrence weight: w(d,e) = c(e,d) / Σ_e' c(e',d) ─────────
        total = max(sum(entity_counts.values()), 1)
        entity_context_weights: dict[str, float] = {
            eid: count / total for eid, count in entity_counts.items()
        }
        uniform = 1.0 / max(len(entities), 1)
        for entity in entities:
            entity_context_weights.setdefault(entity.id, uniform)

        confidence = min(1.0, len(entities) * 0.1) if entities else 0.0

        logger.debug(
            "zeromem_extraction_done",
            extra={
                "context_id": context_id,
                "entity_count": len(entities),
                "confidence": confidence,
            },
        )
        return ExtractionResult(
            source_event_id="",
            context_unit_id=context_id,
            entities=entities,
            relationships=[],
            extraction_confidence=confidence,
            entity_context_weights=entity_context_weights,
        )
