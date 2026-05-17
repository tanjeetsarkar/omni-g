from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

BRIEFING_SCRIPT_LATENCY = Histogram(
    "processor_briefing_script_latency_seconds",
    "Latency of analyst briefing script generation",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

BRIEFING_SCRIPT_ERRORS = Counter(
    "processor_briefing_script_errors_total",
    "Total errors encountered during briefing script generation",
)

_BRIEFING_PROMPT_TEMPLATE = (
    "You are an intelligence analyst. Based on the following community summaries, "
    "write a 3-minute spoken briefing for a senior analyst. Be concise and factual. "
    "Start with 'Good morning. Here is your intelligence briefing.' "
    "Cover the most significant threats, actors, and recommended actions.\n\n"
    "Community summaries:\n{summaries}"
)

_MAX_SUMMARIES_FOR_PROMPT = 10


class BriefingScriptGenerator:
    """Generate analyst briefing scripts from GraphRAG community summaries.

    Uses the LLM extractor's underlying client to generate a spoken briefing
    from the community summaries stored in the graph.  Falls back to
    concatenating the top-5 summaries with section headers when the LLM fails.
    """

    def __init__(self, graphrag_indexer: Any, llm_extractor: Any) -> None:
        self._graphrag_indexer = graphrag_indexer
        self._llm_extractor = llm_extractor

    async def generate(self, tenant_id: str) -> str:
        """Generate a spoken briefing script for *tenant_id*.

        1. Fetches all community summaries from the graph.
        2. Feeds the top-N summaries into the LLM with a briefing prompt.
        3. Returns the full briefing script text.
        4. Fallback: if the LLM fails, concatenates the top-5 summaries.
        """
        t0 = time.perf_counter()
        try:
            summaries = await self._graphrag_indexer.get_community_summaries(tenant_id)
            script = await self._call_llm(summaries)
            BRIEFING_SCRIPT_LATENCY.observe(time.perf_counter() - t0)
            logger.info(
                "briefing_script_generated",
                extra={"tenant_id": tenant_id, "summary_count": len(summaries)},
            )
            return script
        except Exception as exc:  # noqa: BLE001
            BRIEFING_SCRIPT_ERRORS.inc()
            logger.warning(
                "briefing_script_llm_failed_using_fallback",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )
            summaries = await self._graphrag_indexer.get_community_summaries(tenant_id)
            return self._fallback_script(summaries)

    async def _call_llm(self, summaries: list[dict[str, Any]]) -> str:
        """Call the LLM to generate a briefing script from community summaries."""
        top = summaries[:_MAX_SUMMARIES_FOR_PROMPT]
        summary_text = "\n".join(
            f"Community {s.get('community_id', i + 1)}: {s.get('community_summary', '')}"
            for i, s in enumerate(top)
        )
        prompt = _BRIEFING_PROMPT_TEMPLATE.format(
            summaries=summary_text or "No summaries available."
        )

        client = self._llm_extractor._client
        response = await client.chat.completions.create(
            model="qwen2.5:3b",
            messages=[{"role": "user", "content": prompt}],
            response_model=None,
        )
        # instructor wraps the response; handle both raw OpenAI and instructor responses
        if hasattr(response, "choices"):
            return str(response.choices[0].message.content or "")
        return str(response)

    @staticmethod
    def _fallback_script(summaries: list[dict[str, Any]]) -> str:
        """Deterministic fallback: concatenate top-5 summaries with headers."""
        lines = ["Good morning. Here is your intelligence briefing."]
        for i, s in enumerate(summaries[:5], start=1):
            cid = s.get("community_id", i)
            text = s.get("community_summary", "No summary available.")
            lines.append(f"\nSection {i} — Community {cid}:")
            lines.append(str(text))
        if not summaries:
            lines.append("\nNo intelligence data available at this time.")
        return "\n".join(lines)
