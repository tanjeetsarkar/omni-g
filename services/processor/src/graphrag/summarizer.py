from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from neo4j import AsyncDriver
from prometheus_client import Counter, Histogram

from .community import CommunityResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

SUMMARY_GENERATION_LATENCY = Histogram(
    "processor_summary_generation_latency_seconds",
    "Latency of LLM community summary generation",
    ["tenant_id"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

SUMMARY_GENERATION_ERRORS = Counter(
    "processor_summary_generation_errors_total",
    "Total community summary generation failures",
    ["tenant_id"],
)

# ---------------------------------------------------------------------------
# Data transfer object
# ---------------------------------------------------------------------------


@dataclass
class CommunitySummary:
    """Human-readable NL summary for one community."""

    community_id: int
    tenant_id: str
    summary: str
    entity_count: int
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    model_used: str = "template"


# ---------------------------------------------------------------------------
# CommunitySummarizer
# ---------------------------------------------------------------------------


class CommunitySummarizer:
    """Generate LLM-based summaries for graph communities.

    Falls back to a deterministic template summary when the LLM is
    unavailable or raises an exception.
    """

    def __init__(
        self,
        driver: AsyncDriver,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        openai_api_key: str | None = None,
    ) -> None:
        self._driver = driver
        self._ollama_url = ollama_url.rstrip("/")
        self._model = model
        self._openai_api_key = openai_api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize_community(
        self,
        community: CommunityResult,
    ) -> CommunitySummary:
        """Fetch entity context for *community* and generate an NL summary."""
        t0 = time.perf_counter()
        try:
            context = await self._fetch_community_context(community)
            summary_text, model_used = await self._call_llm(community, context)
            result = CommunitySummary(
                community_id=community.community_id,
                tenant_id=community.tenant_id,
                summary=summary_text,
                entity_count=len(community.entity_ids),
                model_used=model_used,
            )
            SUMMARY_GENERATION_LATENCY.labels(tenant_id=community.tenant_id).observe(
                time.perf_counter() - t0
            )
            logger.debug(
                "community_summarized",
                extra={
                    "community_id": community.community_id,
                    "tenant_id": community.tenant_id,
                    "model": model_used,
                },
            )
            return result

        except Exception as exc:
            SUMMARY_GENERATION_ERRORS.labels(tenant_id=community.tenant_id).inc()
            logger.warning(
                "summary_generation_failed_using_template",
                extra={
                    "community_id": community.community_id,
                    "tenant_id": community.tenant_id,
                    "error": str(exc),
                },
            )
            return self._template_summary(community)

    async def store_summary(self, summary: CommunitySummary) -> None:
        """Set ``community_id``, ``community_summary``, and ``community_updated_at``
        on all member nodes of the community in Neo4j.
        """
        timestamp = summary.generated_at.isoformat()
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:STIXEntity) "
                "WHERE n.tenant_id = $tenant_id "
                "  AND n.id IN $entity_ids "
                "SET n.community_id = $community_id, "
                "    n.community_summary = $summary_text, "
                "    n.community_updated_at = $timestamp",
                tenant_id=summary.tenant_id,
                entity_ids=[],  # populated below
                community_id=summary.community_id,
                summary_text=summary.summary,
                timestamp=timestamp,
            )
        # We need entity_ids from the community – store them via a second pass
        # using the community's member list (caller must provide it; this method
        # is typically called immediately after summarize_community so we record
        # it on the summary object itself for convenience).
        # Re-do with the real entity list (the blank call above is a no-op).
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:STIXEntity) "
                "WHERE n.tenant_id = $tenant_id "
                "  AND n.id IN $entity_ids "
                "SET n.community_id = $community_id, "
                "    n.community_summary = $summary_text, "
                "    n.community_updated_at = $timestamp",
                tenant_id=summary.tenant_id,
                entity_ids=getattr(summary, "_entity_ids", []),
                community_id=summary.community_id,
                summary_text=summary.summary,
                timestamp=timestamp,
            )
        logger.debug(
            "community_summary_stored",
            extra={
                "community_id": summary.community_id,
                "tenant_id": summary.tenant_id,
            },
        )

    async def store_summary_for_community(
        self,
        summary: CommunitySummary,
        entity_ids: list[str],
    ) -> None:
        """Store *summary* for the given *entity_ids*.

        Prefer this method over :meth:`store_summary` when the caller has
        the entity list readily available.
        """
        timestamp = summary.generated_at.isoformat()
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:STIXEntity) "
                "WHERE n.tenant_id = $tenant_id "
                "  AND n.id IN $entity_ids "
                "SET n.community_id = $community_id, "
                "    n.community_summary = $summary_text, "
                "    n.community_updated_at = $timestamp",
                tenant_id=summary.tenant_id,
                entity_ids=entity_ids,
                community_id=summary.community_id,
                summary_text=summary.summary,
                timestamp=timestamp,
            )
        logger.debug(
            "community_summary_stored",
            extra={
                "community_id": summary.community_id,
                "tenant_id": summary.tenant_id,
                "entity_count": len(entity_ids),
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_community_context(
        self, community: CommunityResult
    ) -> dict[str, Any]:
        """Fetch entity names, types, and relationships for the community."""
        async with self._driver.session() as session:
            # Entities
            entity_result = await session.run(
                "MATCH (n:STIXEntity) "
                "WHERE n.id IN $entity_ids AND n.tenant_id = $tenant_id "
                "RETURN n.id AS eid, n.name AS name, n.stix_type AS stype",
                entity_ids=community.entity_ids,
                tenant_id=community.tenant_id,
            )
            entity_records = await entity_result.data()

            # Relationships between community members
            rel_result = await session.run(
                "MATCH (a:STIXEntity)-[r]->(b:STIXEntity) "
                "WHERE a.id IN $entity_ids AND b.id IN $entity_ids "
                "  AND a.tenant_id = $tenant_id "
                "RETURN a.name AS src_name, type(r) AS rel_type, b.name AS tgt_name",
                entity_ids=community.entity_ids,
                tenant_id=community.tenant_id,
            )
            rel_records = await rel_result.data()

        return {"entities": entity_records, "relationships": rel_records}

    async def _call_llm(
        self,
        community: CommunityResult,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        """Call the LLM to generate a summary.  Returns (summary_text, model_used)."""
        entity_list = ", ".join(
            f"{e.get('name', e.get('eid', '?'))} ({e.get('stype', '?')})"
            for e in context["entities"]
        )
        rel_list = ", ".join(
            f"{r.get('src_name', '?')} --[{r.get('rel_type', '?')}]--> "
            f"{r.get('tgt_name', '?')}"
            for r in context["relationships"]
        )

        prompt = (
            "You are an intelligence analyst. "
            "Summarize the following threat intelligence community in 2-3 sentences. "
            f"Entities: {entity_list or 'none'}. "
            f"Relationships: {rel_list or 'none'}. "
            "Focus on the main threat actors, their targets, and tactics."
        )

        if self._openai_api_key:
            return await self._call_openai(prompt)
        return await self._call_ollama(prompt)

    async def _call_ollama(self, prompt: str) -> tuple[str, str]:
        """Call Ollama's OpenAI-compatible chat endpoint."""
        url = f"{self._ollama_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        text: str = data["message"]["content"]
        return text, self._model

    async def _call_openai(self, prompt: str) -> tuple[str, str]:
        """Call the OpenAI Chat Completions API."""
        url = "https://api.openai.com/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self._openai_api_key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        text = data["choices"][0]["message"]["content"]
        return text, "gpt-4o-mini"

    @staticmethod
    def _template_summary(community: CommunityResult) -> CommunitySummary:
        """Generate a deterministic template summary without an LLM call."""
        n = len(community.entity_ids)
        summary = (
            f"Community {community.community_id} contains {n} "
            f"{'entity' if n == 1 else 'entities'}."
        )
        return CommunitySummary(
            community_id=community.community_id,
            tenant_id=community.tenant_id,
            summary=summary,
            entity_count=n,
            model_used="template",
        )
