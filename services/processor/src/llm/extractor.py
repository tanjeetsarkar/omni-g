from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..models.stix import (
    AttackPattern,
    Campaign,
    ExtractionResult,
    Identity,
    Indicator,
    Location,
    Malware,
    Relationship,
    STIXType,
    ThreatActor,
)
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


class _LLMEntityBase(BaseModel):
    """Minimal base for LLM-extracted entities.

    Only captures what a small model can reliably produce.
    STIX IDs, created/modified timestamps are generated during normalisation.
    """

    model_config = ConfigDict(extra="ignore")

    id: str | None = None  # LLM's internal cross-ref (not a STIX UUID)
    name: str = "Unknown"
    confidence: int | None = None


class _LLMThreatActor(_LLMEntityBase):
    aliases: list[str] = Field(default_factory=list)
    threat_actor_types: list[str] = Field(default_factory=list)
    description: str | None = None


class _LLMMalware(_LLMEntityBase):
    malware_types: list[str] = Field(default_factory=list)
    is_family: bool = False
    description: str | None = None


class _LLMIdentity(_LLMEntityBase):
    identity_class: str = "unknown"
    sectors: list[str] = Field(default_factory=list)


class _LLMAttackPattern(_LLMEntityBase):
    description: str | None = None


class _LLMCampaign(_LLMEntityBase):
    description: str | None = None


class _LLMIndicator(_LLMEntityBase):
    indicator_types: list[str] = Field(default_factory=list)
    pattern: str | None = None
    valid_from: str | None = None


class _LLMLocation(_LLMEntityBase):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    country: str | None = None
    region: str | None = None
    latitude: float | None = Field(default=None, validation_alias=AliasChoices("latitude", "lat"))
    longitude: float | None = Field(default=None, validation_alias=AliasChoices("longitude", "lon"))


class _LLMRelationship(BaseModel):
    """Accepts the loose field names that small LLMs tend to output."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    relationship_type: str = Field(
        default="related-to",
        validation_alias=AliasChoices("relationship_type", "type"),
    )
    source_ref: str = Field(
        default="",
        validation_alias=AliasChoices("source_ref", "source_id"),
    )
    target_ref: str = Field(
        default="",
        validation_alias=AliasChoices("target_ref", "target_id"),
    )
    description: str | None = None
    confidence: int | None = None

    @field_validator("source_ref", "target_ref", mode="before")
    @classmethod
    def _coerce_none_to_empty(cls, v: Any) -> str:
        return v if v is not None else ""


class _LLMEntities(BaseModel):
    """Internal model used as instructor response_model.

    Holds only the entity/relationship lists so the LLM never has to fill
    derived fields (source_event_id, extraction_confidence, plugin_*).
    Uses simplified extraction types — STIX normalisation happens in
    _normalize_llm_entities() after the LLM call.
    """

    threat_actors: list[_LLMThreatActor] = Field(default_factory=list)
    malware: list[_LLMMalware] = Field(default_factory=list)
    identities: list[_LLMIdentity] = Field(default_factory=list)
    attack_patterns: list[_LLMAttackPattern] = Field(default_factory=list)
    campaigns: list[_LLMCampaign] = Field(default_factory=list)
    indicators: list[_LLMIndicator] = Field(default_factory=list)
    locations: list[_LLMLocation] = Field(default_factory=list)
    relationships: list[_LLMRelationship] = Field(default_factory=list)


def _parse_dt(value: str | None) -> datetime | None:
    """Best-effort parse of a datetime string from LLM output."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _normalize_llm_entities(raw: _LLMEntities) -> dict[str, list[Any]]:
    """Convert simplified LLM extraction output into fully-valid STIX objects.

    Generates STIX-compliant UUIDs and timestamps, resolves internal cross-refs
    in relationships, and drops relationships with unresolvable refs.
    """
    now = datetime.now(UTC)
    id_map: dict[str, str] = {}

    def _make_id(stix_type: str, llm_id: str | None) -> str:
        stix_id = f"{stix_type}--{uuid4()}"
        if llm_id:
            id_map[llm_id] = stix_id
        return stix_id

    threat_actors = [
        ThreatActor(
            type=STIXType.THREAT_ACTOR,
            id=_make_id("threat-actor", e.id),
            created=now,
            modified=now,
            name=e.name,
            aliases=e.aliases,
            threat_actor_types=e.threat_actor_types,
            description=e.description,
            confidence=e.confidence,
        )
        for e in raw.threat_actors
    ]

    malware = [
        Malware(
            type=STIXType.MALWARE,
            id=_make_id("malware", e.id),
            created=now,
            modified=now,
            name=e.name,
            malware_types=e.malware_types,
            is_family=e.is_family,
            description=e.description,
            confidence=e.confidence,
        )
        for e in raw.malware
    ]

    identities = [
        Identity(
            type=STIXType.IDENTITY,
            id=_make_id("identity", e.id),
            created=now,
            modified=now,
            name=e.name,
            identity_class=e.identity_class,
            sectors=e.sectors,
            confidence=e.confidence,
        )
        for e in raw.identities
    ]

    attack_patterns = [
        AttackPattern(
            type=STIXType.ATTACK_PATTERN,
            id=_make_id("attack-pattern", e.id),
            created=now,
            modified=now,
            name=e.name,
            description=e.description,
            confidence=e.confidence,
        )
        for e in raw.attack_patterns
    ]

    campaigns = [
        Campaign(
            type=STIXType.CAMPAIGN,
            id=_make_id("campaign", e.id),
            created=now,
            modified=now,
            name=e.name,
            description=e.description,
            confidence=e.confidence,
        )
        for e in raw.campaigns
    ]

    indicators = [
        Indicator(
            type=STIXType.INDICATOR,
            id=_make_id("indicator", e.id),
            created=now,
            modified=now,
            name=e.name,
            indicator_types=e.indicator_types,
            pattern=e.pattern or "[unknown:value = 'unknown']",
            valid_from=_parse_dt(e.valid_from) or now,
            confidence=e.confidence,
        )
        for e in raw.indicators
    ]

    locations = [
        Location(
            type=STIXType.LOCATION,
            id=_make_id("location", e.id),
            created=now,
            modified=now,
            name=e.name,
            country=e.country,
            region=e.region,
            latitude=e.latitude,
            longitude=e.longitude,
            confidence=e.confidence,
        )
        for e in raw.locations
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
        relationships.append(
            Relationship(
                type="relationship",
                id=f"relationship--{uuid4()}",
                created=now,
                modified=now,
                relationship_type=r.relationship_type,
                source_ref=src,
                target_ref=tgt,
                description=r.description,
                confidence=r.confidence,
            )
        )

    return {
        "threat_actors": threat_actors,
        "malware": malware,
        "identities": identities,
        "attack_patterns": attack_patterns,
        "campaigns": campaigns,
        "indicators": indicators,
        "locations": locations,
        "relationships": relationships,
    }


class LLMExtractor:
    """
    Extracts STIX entities from raw text using PydanticAI.

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
        """Extract STIX entities from text, with automatic fallback on LLM errors."""
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
                "threat_actors": len(result.threat_actors),
                "malware": len(result.malware),
                "identities": len(result.identities),
                "attack_patterns": len(result.attack_patterns),
                "campaigns": len(result.campaigns),
                "indicators": len(result.indicators),
                "locations": len(result.locations),
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
                "threat_actors": len(result.threat_actors),
                "malware": len(result.malware),
                "identities": len(result.identities),
                "attack_patterns": len(result.attack_patterns),
                "campaigns": len(result.campaigns),
                "indicators": len(result.indicators),
                "locations": len(result.locations),
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
        all_lists: tuple[Sequence[object], ...] = (
            entities.threat_actors,
            entities.malware,
            entities.identities,
            entities.attack_patterns,
            entities.campaigns,
            entities.indicators,
            entities.locations,
        )
        total = sum(len(lst) for lst in all_lists)
        if total == 0:
            return 0.0
        diversity = sum(1 for lst in all_lists if lst)
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
