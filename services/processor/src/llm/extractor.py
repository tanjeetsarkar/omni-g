from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..models.entities import Entity, EvidenceSpan, ExtractionResult, Relationship
from .prompts import PromptRegistry

logger = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────
_ollama_url = os.getenv("OLLAMA_URL")
LLM_BASE_URL: str = os.getenv(
    "LLM_BASE_URL",
    f"{_ollama_url.rstrip('/')}/v1" if _ollama_url else "http://localhost:11434/v1",
)
LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))
LLM_FALLBACK_MODEL: str = os.getenv(
    "LLM_FALLBACK_MODEL",
    os.getenv("OLLAMA_FALLBACK_MODEL", "qwen2.5:3b"),
)
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_RATE_LIMIT_RPS: int = int(os.getenv("LLM_RATE_LIMIT_RPS", "10"))

# System prompts are now managed by PromptRegistry in prompts.py.
# The constants below are kept for backward compatibility in tests that
# import them directly.
_SYSTEM_FALLBACK = PromptRegistry.SYSTEM_PROMPT_FALLBACK


class _LLMEntity(BaseModel):
    """Generic LLM-extracted entity.

    The LLM assigns ``type`` freely from context (Person, Organization, Event, …).
    Entity IDs and timestamps are generated during normalisation.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None  # LLM's internal cross-ref (not a real UUID)
    type: str = "Unknown"  # LLM determines this freely
    name: str = "Unknown"
    description: str | None = None
    confidence: float | None = None  # 0.0–1.0
    properties: dict[str, Any] = Field(default_factory=dict)
    source_span: str | None = None  # Verbatim excerpt from source text naming this entity


class _LLMRelationship(BaseModel):
    """Accepts the loose field names that small LLMs tend to output."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str = Field(
        default="RELATED_TO",
        validation_alias=AliasChoices("type", "relationship_type"),
    )
    source_ref: str = Field(
        default="",
        validation_alias=AliasChoices("source_ref", "source_id"),
    )
    target_ref: str = Field(
        default="",
        validation_alias=AliasChoices("target_ref", "target_id"),
    )
    confidence: float | None = None

    @field_validator("source_ref", "target_ref", mode="before")
    @classmethod
    def _coerce_none_to_empty(cls, v: Any) -> str:
        return v if v is not None else ""


class _LLMEntities(BaseModel):
    """Internal model used as pydantic-ai output_type.

    Holds only the entity/relationship lists so the LLM never has to fill
    derived fields (source_event_id, extraction_confidence, plugin_*).
    """

    entities: list[_LLMEntity] = Field(default_factory=list)
    relationships: list[_LLMRelationship] = Field(default_factory=list)


def _normalize_llm_entities(raw: _LLMEntities) -> dict[str, list[Any]]:
    """Convert generic LLM extraction output into fully-validated Entity/Relationship objects.

    Generates UUID-based IDs, resolves internal cross-refs in relationships,
    and drops relationships with unresolvable refs.
    """
    now = datetime.now(UTC)
    id_map: dict[str, str] = {}

    def _make_id(llm_id: str | None) -> str:
        entity_id = f"entity--{uuid4()}"
        if llm_id:
            id_map[llm_id] = entity_id
        return entity_id

    entities: list[Entity] = [
        Entity(
            id=_make_id(e.id),
            type=e.type or "Unknown",
            name=e.name or "Unknown",
            description=e.description,
            properties=e.properties,
            confidence=e.confidence if e.confidence is not None else 0.5,
            tenant_id="",  # filled in by the pipeline from the envelope
            source_id=None,  # filled in by the pipeline from the envelope
            source_spans=([EvidenceSpan(text=e.source_span)] if e.source_span else []),
            created=now,
            modified=now,
        )
        for e in raw.entities
    ]

    relationships: list[Relationship] = []
    for r in raw.relationships:
        src = id_map.get(r.source_ref, r.source_ref)
        tgt = id_map.get(r.target_ref, r.target_ref)
        if not src or not tgt:
            logger.debug(
                "Dropping relationship with unresolvable ref: %s → %s", r.source_ref, r.target_ref
            )
            continue
        # Normalise relationship type to UPPER_SNAKE_CASE
        rel_type = re.sub(r"[^a-zA-Z0-9_]", "_", r.type).upper() if r.type else "RELATED_TO"
        relationships.append(
            Relationship(
                id=f"relationship--{uuid4()}",
                type=rel_type,
                source_ref=src,
                target_ref=tgt,
                confidence=r.confidence if r.confidence is not None else 0.5,
                tenant_id="",  # filled in by the pipeline
                created=now,
                modified=now,
            )
        )

    return {
        "entities": entities,
        "relationships": relationships,
    }


class LLMExtractor:
    """
    Extracts generic entities from raw text using PydanticAI.

    Config is read from environment variables at construction time:
            LLM_BASE_URL/OLLAMA_URL, LLM_MODEL/OLLAMA_MODEL,
            LLM_FALLBACK_MODEL/OLLAMA_FALLBACK_MODEL, LLM_TIMEOUT_SECONDS,
      LLM_MAX_TOKENS, LLM_RATE_LIMIT_RPS.
    """

    def __init__(self) -> None:
        self._openai_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
        self._provider = OpenAIProvider(openai_client=self._openai_client)
        self._primary_model = OpenAIChatModel(LLM_MODEL, provider=self._provider)
        self._fallback_model = OpenAIChatModel(LLM_FALLBACK_MODEL, provider=self._provider)
        self._semaphore = asyncio.Semaphore(LLM_RATE_LIMIT_RPS)

    async def extract(
        self,
        event_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Extract entities from text, with automatic fallback on LLM errors."""
        source_type: str = (metadata.get("source_type") or "general") if metadata else "general"
        async with self._semaphore:
            entities = await self._try_extract(text, source_type)

        confidence = self._calculate_confidence(entities, source_type)
        normalized = _normalize_llm_entities(entities)
        return ExtractionResult(
            source_event_id=event_id,
            extraction_confidence=confidence,
            plugin_id=metadata.get("plugin_id") if metadata else None,
            plugin_version=metadata.get("plugin_version") if metadata else None,
            **normalized,
        )

    async def _try_extract(self, text: str, source_type: str = "general") -> _LLMEntities:
        """Try primary model; fall back, then degrade to empty entities on recoverable errors."""
        try:
            return await self._call_primary(text, source_type)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "llm_primary_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc), "model": LLM_MODEL},
            )
            try:
                return await self._call_fallback(text, source_type)
            except asyncio.CancelledError:
                raise
            except Exception as exc2:
                logger.error(
                    "llm_fallback_failed",
                    extra={
                        "error_type": type(exc2).__name__,
                        "error": str(exc2),
                        "model": LLM_FALLBACK_MODEL,
                    },
                )
                return _LLMEntities()

    async def _call_primary(self, text: str, source_type: str = "general") -> _LLMEntities:
        system_prompt = PromptRegistry.get_prompt(source_type)
        logger.info(
            "llm_call_start",
            extra={
                "model": LLM_MODEL,
                "endpoint": LLM_BASE_URL,
                "source_type": source_type,
                "text_length": len(text),
                "max_tokens": LLM_MAX_TOKENS,
            },
        )
        logger.debug(
            "llm_call_messages",
            extra={"system_prompt": system_prompt, "user_text": text},
        )
        t0 = time.monotonic()
        agent = Agent(
            self._primary_model,
            system_prompt=system_prompt,
            output_type=_LLMEntities,
            retries=3,
        )
        run_res = await agent.run(text)
        result = run_res.output
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "llm_call_done",
            extra={
                "model": LLM_MODEL,
                "endpoint": LLM_BASE_URL,
                "duration_ms": duration_ms,
                "entities": len(result.entities),
                "relationships": len(result.relationships),
            },
        )
        return result

    async def _call_fallback(self, text: str, source_type: str = "general") -> _LLMEntities:  # noqa: ARG002
        system_prompt = PromptRegistry.SYSTEM_PROMPT_FALLBACK
        logger.info(
            "llm_call_start",
            extra={
                "model": LLM_FALLBACK_MODEL,
                "endpoint": LLM_BASE_URL,
                "source_type": source_type,
                "text_length": len(text),
                "max_tokens": LLM_MAX_TOKENS,
                "fallback": True,
            },
        )
        logger.debug(
            "llm_call_messages",
            extra={"system_prompt": system_prompt, "user_text": text},
        )
        t0 = time.monotonic()
        agent = Agent(
            self._fallback_model,
            system_prompt=system_prompt,
            output_type=_LLMEntities,
            retries=3,
        )
        run_res = await agent.run(text)
        result = run_res.output
        duration_ms = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "llm_call_done",
            extra={
                "model": LLM_FALLBACK_MODEL,
                "endpoint": LLM_BASE_URL,
                "duration_ms": duration_ms,
                "entities": len(result.entities),
                "relationships": len(result.relationships),
                "fallback": True,
            },
        )
        return result

    def _calculate_confidence(self, entities: _LLMEntities, source_type: str = "general") -> float:
        """Scale confidence 0→1 based on entity count and type diversity.

        Authoritative structured sources (biographical, wikidata) receive a +0.1
        boost because their facts are explicitly asserted rather than inferred.
        """
        total = len(entities.entities)
        if total == 0:
            return 0.0
        # Diversity = number of unique non-Unknown entity types
        types = {e.type for e in entities.entities if e.type and e.type != "Unknown"}
        diversity = len(types)
        base = min(1.0, total * 0.1 + diversity * 0.05)
        boost = 0.1 if source_type in ("biographical", "wikidata") else 0.0
        return min(1.0, base + boost)

    async def extract_batch(self, events: list[dict[str, Any]]) -> list[ExtractionResult]:
        """Extract entities from multiple events concurrently.

        Exceptions from individual extractions are captured via
        ``return_exceptions=True`` and converted to empty ExtractionResult
        objects so the caller always receives a full-length list.
        """
        tasks = [
            self.extract(
                event_id=event.get("id", ""),
                text=event.get("text", ""),
                metadata=event.get("metadata"),
            )
            for event in events
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r
            if isinstance(r, ExtractionResult)
            else ExtractionResult(
                source_event_id=events[i].get("id", ""),
                extraction_confidence=0.0,
            )
            for i, r in enumerate(raw)
        ]
