"""Analyst briefing script generator (V3).

V3 NOTE: The GraphRAG CommunitySummarizer content source was removed.
The natural V3 replacement is calibrated R(q) context arrays from the
Dual-View Retrieval Engine — treat as follow-on work after Phase 6.
For now the generator produces a placeholder script via LLM calls.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import Counter, Histogram

from ..llm.client import LLMClient

logger = logging.getLogger(__name__)

BRIEFING_SCRIPT_LATENCY = Histogram(
    "processor_briefing_script_latency_seconds",
    "Latency of analyst briefing script generation",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

BRIEFING_SCRIPT_ERRORS = Counter(
    "processor_briefing_script_errors_total",
    "Total errors encountered during briefing script generation",
)

_BRIEFING_PROMPT = (
    "You are an intelligence analyst. Write a 3-minute spoken briefing for a senior analyst. "
    "Be concise and factual. Start with 'Good morning. Here is your intelligence briefing.' "
    "Cover the most significant findings and recommended actions.\n\n"
    "Context summaries:\n{context}"
)


class BriefingScriptGenerator:
    """Generate analyst briefing scripts.

    In V3 the *context* is provided externally (e.g. calibrated R(q) arrays).
    Falls back to a placeholder when no context is available.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._llm_client = llm_client or LLMClient()

    async def generate(self, tenant_id: str, context: list[dict[str, Any]] | None = None) -> str:
        """Generate a spoken briefing script for *tenant_id*.

        *context* should be a list of dicts with a ``text`` key (calibrated R(q) output).
        Falls back to a placeholder when context is empty or unavailable.
        """
        t0 = time.perf_counter()
        summaries = context or []
        try:
            if summaries:
                script = await self._call_llm(summaries)
            else:
                script = self._placeholder_script(tenant_id)
            BRIEFING_SCRIPT_LATENCY.observe(time.perf_counter() - t0)
            logger.info(
                "briefing_script_generated",
                extra={"tenant_id": tenant_id, "context_count": len(summaries)},
            )
            return script
        except Exception as exc:  # noqa: BLE001
            BRIEFING_SCRIPT_ERRORS.inc()
            logger.warning(
                "briefing_script_failed_using_placeholder",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )
            return self._placeholder_script(tenant_id)

    async def _call_llm(self, summaries: list[dict[str, Any]]) -> str:
        top = summaries[:10]
        context_text = "\n".join(
            f"[{i + 1}] {s.get('text', s.get('community_summary', ''))}" for i, s in enumerate(top)
        )
        prompt = _BRIEFING_PROMPT.format(context=context_text or "No context available.")

        return await self._llm_client.generate(prompt)

    @staticmethod
    def _placeholder_script(tenant_id: str) -> str:
        return (
            "Good morning. Here is your intelligence briefing.\n\n"
            f"Briefing for tenant '{tenant_id}': No context data is currently available. "
            "The V3 Zero-Mem calibrated context source is pending integration with the "
            "Dual-View Retrieval Engine output. Please check back after Phase 6 is complete."
        )

    @staticmethod
    def _fallback_script(summaries: list[dict[str, Any]]) -> str:
        lines = ["Good morning. Here is your intelligence briefing."]
        for i, s in enumerate(summaries[:5], start=1):
            text = s.get("text") or s.get("community_summary", "No summary available.")
            lines.append(f"\nSection {i}:\n{text}")
        if not summaries:
            lines.append("\nNo intelligence data available at this time.")
        return "\n".join(lines)
