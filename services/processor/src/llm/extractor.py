from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Sequence
from typing import Any

import instructor
import openai
from pydantic import BaseModel, Field

from ..models.stix import (
    AttackPattern,
    Campaign,
    ExtractionResult,
    Identity,
    Indicator,
    Location,
    Malware,
    Relationship,
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


class _LLMEntities(BaseModel):
    """Internal model used as instructor response_model.

    Holds only the entity/relationship lists so the LLM never has to fill
    derived fields (source_event_id, extraction_confidence, plugin_*).
    """

    threat_actors: list[ThreatActor] = Field(default_factory=list)
    malware: list[Malware] = Field(default_factory=list)
    identities: list[Identity] = Field(default_factory=list)
    attack_patterns: list[AttackPattern] = Field(default_factory=list)
    campaigns: list[Campaign] = Field(default_factory=list)
    indicators: list[Indicator] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class LLMExtractor:
    """
    Extracts STIX entities from raw text using an LLM via the instructor library.

    Config is read from environment variables at construction time:
            LLM_BASE_URL/OLLAMA_URL, LLM_MODEL/OLLAMA_MODEL,
            LLM_FALLBACK_MODEL/OLLAMA_FALLBACK_MODEL, LLM_TIMEOUT_SECONDS,
      LLM_MAX_TOKENS, LLM_RATE_LIMIT_RPS.
    """

    def __init__(self) -> None:
        self._client = instructor.from_openai(
            openai.AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama"),
            mode=instructor.Mode.JSON,
        )
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
        return ExtractionResult(
            source_event_id=event_id,
            threat_actors=entities.threat_actors,
            malware=entities.malware,
            identities=entities.identities,
            attack_patterns=entities.attack_patterns,
            campaigns=entities.campaigns,
            indicators=entities.indicators,
            locations=entities.locations,
            relationships=entities.relationships,
            extraction_confidence=confidence,
            plugin_id=metadata.get("plugin_id") if metadata else None,
            plugin_version=metadata.get("plugin_version") if metadata else None,
        )

    async def _try_extract(self, text: str, source_type: str = "general") -> _LLMEntities:
        """Try primary model; fall back to fallback model on API error."""
        try:
            return await self._call_primary(text, source_type)
        except (TimeoutError, openai.APIError) as exc:
            logger.warning(
                "llm_primary_failed",
                extra={"error_type": type(exc).__name__, "error": str(exc), "model": LLM_MODEL},
            )
            try:
                return await self._call_fallback(text, source_type)
            except (TimeoutError, openai.APIError) as exc2:
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
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
        result = await self._client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            response_model=_LLMEntities,
            max_tokens=LLM_MAX_TOKENS,
        )
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
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
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
        result = await self._client.chat.completions.create(
            model=LLM_FALLBACK_MODEL,
            messages=messages,
            response_model=_LLMEntities,
            max_tokens=LLM_MAX_TOKENS,
        )
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
