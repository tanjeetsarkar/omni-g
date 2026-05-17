from __future__ import annotations

import asyncio
import logging
import os
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

logger = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2:3b")
LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", "llama3.1:8b")
LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "10"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_RATE_LIMIT_RPS: int = int(os.getenv("LLM_RATE_LIMIT_RPS", "10"))

_SYSTEM_PRIMARY = (
    "You are a STIX 2.1 threat intelligence extractor. "
    "Extract all entities from the text and return structured JSON matching the ExtractionResult \
        schema."
)
_SYSTEM_FALLBACK = (
    "Extract threat actors and malware from this text. "
    "Return JSON with threat_actors and malware arrays."
)


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
      LLM_BASE_URL, LLM_MODEL, LLM_FALLBACK_MODEL, LLM_TIMEOUT_SECONDS,
      LLM_MAX_TOKENS, LLM_RATE_LIMIT_RPS.
    """

    def __init__(self) -> None:
        self._client = instructor.from_openai(
            openai.AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
        )
        self._semaphore = asyncio.Semaphore(LLM_RATE_LIMIT_RPS)

    async def extract(
        self,
        event_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Extract STIX entities from text, with automatic fallback on LLM errors."""
        async with self._semaphore:
            entities = await self._try_extract(text)

        confidence = self._calculate_confidence(entities)
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

    async def _try_extract(self, text: str) -> _LLMEntities:
        """Try primary model; fall back to fallback model on timeout/API error."""
        try:
            return await asyncio.wait_for(
                self._call_primary(text),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except (TimeoutError, openai.APIError) as exc:
            logger.warning("Primary LLM failed (%s), trying fallback", type(exc).__name__)
            try:
                return await asyncio.wait_for(
                    self._call_fallback(text),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except (TimeoutError, openai.APIError) as exc2:
                logger.error(
                    "Fallback LLM also failed (%s), returning empty entities",
                    type(exc2).__name__,
                )
                return _LLMEntities()

    async def _call_primary(self, text: str) -> _LLMEntities:
        return await self._client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PRIMARY},
                {"role": "user", "content": text},
            ],
            response_model=_LLMEntities,
            max_tokens=LLM_MAX_TOKENS,
        )

    async def _call_fallback(self, text: str) -> _LLMEntities:
        return await self._client.chat.completions.create(
            model=LLM_FALLBACK_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_FALLBACK},
                {"role": "user", "content": text},
            ],
            response_model=_LLMEntities,
            max_tokens=LLM_MAX_TOKENS,
        )

    def _calculate_confidence(self, entities: _LLMEntities) -> float:
        """Scale confidence 0→1 based on entity count and type diversity."""
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
        return min(1.0, total * 0.1 + diversity * 0.05)

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
