"""V2 Step 7 — First-pass Assessment generation.

Produces an :class:`~src.models.entities.Assessment` (BLUF + confidence band +
evidence linkage + intelligence gaps) for each pipeline run that carries a
``kiq_id`` and at least one grounded :class:`~src.models.entities.CollectedEvidence`
object.

On LLM failure the service falls back to a rule-based degenerate assessment so
the pipeline always produces an output when evidence is present.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..models.entities import Assessment, CollectedEvidence, CollectionGap, ConfidenceBand

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM configuration — mirrors extractor.py so all analytical calls share the
# same model endpoint and identity.
# ---------------------------------------------------------------------------

_ollama_url = os.getenv("OLLAMA_URL")
LLM_BASE_URL: str = os.getenv(
    "LLM_BASE_URL",
    f"{_ollama_url.rstrip('/')}/v1" if _ollama_url else "http://localhost:11434/v1",
)
LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))

_ASSESSMENT_SYSTEM_PROMPT = """\
You are an intelligence analyst. Given a Key Intelligence Question (KIQ) ID and a \
numbered list of collected evidence, produce a structured first-pass assessment.

Assessment rules:
- BLUF first: state the bottom-line conclusion in one clear declarative sentence.
- Express confidence as three float values: low (conservative), mid (point estimate), \
high (optimistic), all between 0.0 and 1.0.
- Explain your reasoning in 2-5 sentences.
- List key assumptions (what had to be true for this conclusion to hold).
- Identify which evidence indices (0-based) most support the conclusion.
- Identify which evidence indices (0-based) complicate or contradict the conclusion.
- Identify 1-3 collection gaps: specific missing information that would raise confidence.
- Recommend 1-3 concrete next actions.

STRUCTURAL RULES:
- conclusion must be a non-empty declarative statement.
- confidence values must satisfy: 0.0 <= low <= mid <= high <= 1.0.
- evidence indices are 0-based integers referencing the input evidence list.
- gap statements must be specific and actionable.
"""


# ---------------------------------------------------------------------------
# Internal LLM output models
# ---------------------------------------------------------------------------


class _LLMGap(BaseModel):
    """Single collection gap identified by the LLM."""

    statement: str
    why_needed: str
    suggested_sources: list[str] = Field(default_factory=list)
    suggested_plugins: list[str] = Field(default_factory=list)


class _LLMAssessmentOutput(BaseModel):
    """Structured output returned by the assessment LLM call."""

    conclusion: str
    confidence_low: float = Field(default=0.3, ge=0.0, le=1.0)
    confidence_mid: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_high: float = Field(default=0.7, ge=0.0, le=1.0)
    reasoning: str
    assumptions: list[str] = Field(default_factory=list)
    supporting_evidence_indices: list[int] = Field(default_factory=list)
    contradicting_evidence_indices: list[int] = Field(default_factory=list)
    gaps: list[_LLMGap] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AssessmentService
# ---------------------------------------------------------------------------


class AssessmentService:
    """Generates first-pass V2 Assessment objects from collected evidence.

    Called by :class:`~src.processor.pipeline.ProcessingPipeline` after the
    evidence-creation stage (step 3.6) when a ``kiq_id`` is present on the
    incoming event.  Produces one :class:`~src.models.entities.Assessment` and
    zero or more :class:`~src.models.entities.CollectionGap` records per call.

    The service uses the same LLM endpoint as the entity extractor so no extra
    runtime dependency is introduced.  On LLM failure it falls back to a
    rule-based degenerate assessment, ensuring the pipeline always produces
    output when evidence is present.
    """

    def __init__(self) -> None:
        self._openai_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
        self._provider = OpenAIProvider(openai_client=self._openai_client)
        self._model = OpenAIChatModel(LLM_MODEL, provider=self._provider)

    async def generate(
        self,
        kiq_id: str,
        tenant_id: str,
        evidence_list: list[CollectedEvidence],
    ) -> tuple[Assessment, list[CollectionGap]] | None:
        """Generate a first-pass Assessment for the given KIQ and evidence.

        Returns ``(Assessment, gaps)`` when evidence is present, ``None`` when
        ``evidence_list`` is empty (nothing to assess).  On LLM failure, falls
        back to the rule-based degenerate assessment rather than returning
        ``None``.
        """
        if not evidence_list:
            return None

        evidence_summary = self._build_evidence_summary(evidence_list)
        user_prompt = (
            f"KIQ ID: {kiq_id}\n"
            f"Evidence count: {len(evidence_list)}\n\n"
            f"Evidence:\n{evidence_summary}"
        )

        try:
            llm_result = await self._call_llm(user_prompt)
        except Exception as exc:
            logger.warning(
                "assessment_llm_failed",
                extra={"kiq_id": kiq_id, "error_type": type(exc).__name__, "error": str(exc)},
            )
            llm_result = self._degenerate_assessment(evidence_list)

        return self._build_assessment_and_gaps(kiq_id, tenant_id, evidence_list, llm_result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_evidence_summary(self, evidence_list: list[CollectedEvidence]) -> str:
        lines: list[str] = []
        for i, ev in enumerate(evidence_list):
            credibility = ev.information_credibility.value
            lines.append(
                f"[{i}] {ev.assertion} "
                f"(credibility={credibility}, confidence={ev.extraction_confidence:.2f})"
            )
        return "\n".join(lines)

    async def _call_llm(self, user_prompt: str) -> _LLMAssessmentOutput:
        agent: Agent[None, _LLMAssessmentOutput] = Agent(
            self._model,
            system_prompt=_ASSESSMENT_SYSTEM_PROMPT,
            output_type=_LLMAssessmentOutput,
            retries=2,
        )
        run_res = await agent.run(user_prompt)
        return run_res.output

    def _degenerate_assessment(
        self, evidence_list: list[CollectedEvidence]
    ) -> _LLMAssessmentOutput:
        """Rule-based fallback used when the LLM is unavailable or times out."""
        n = len(evidence_list)
        confidence_vals = [ev.extraction_confidence for ev in evidence_list]
        avg_conf = sum(confidence_vals) / len(confidence_vals) if confidence_vals else 0.5
        low = round(max(0.0, avg_conf - 0.2), 2)
        high = round(min(1.0, avg_conf + 0.2), 2)
        mid = round(avg_conf, 2)
        return _LLMAssessmentOutput(
            conclusion=(
                f"Assessment based on {n} evidence item(s) collected against KIQ "
                "(LLM unavailable; rule-based fallback)."
            ),
            confidence_low=low,
            confidence_mid=mid,
            confidence_high=high,
            reasoning=(
                f"{n} evidence item(s) were extracted and scored. "
                f"Average extraction confidence: {avg_conf:.2f}."
            ),
            assumptions=["Evidence is representative of available sources."],
            supporting_evidence_indices=list(range(min(n, 3))),
            contradicting_evidence_indices=[],
            gaps=[
                _LLMGap(
                    statement="Additional source coverage needed for higher confidence.",
                    why_needed=(
                        "Current evidence count is insufficient "
                        "to reach a high-confidence conclusion."
                    ),
                )
            ],
            recommended_next_actions=["Collect additional evidence against this KIQ."],
        )

    def _build_assessment_and_gaps(
        self,
        kiq_id: str,
        tenant_id: str,
        evidence_list: list[CollectedEvidence],
        llm_result: _LLMAssessmentOutput,
    ) -> tuple[Assessment, list[CollectionGap]]:
        now = datetime.now(UTC)
        assessment_id = f"assessment--{uuid4()}"
        n = len(evidence_list)

        # Resolve evidence indices to IDs; silently skip out-of-range indices.
        supporting_ids = [
            evidence_list[i].id for i in llm_result.supporting_evidence_indices if 0 <= i < n
        ]
        contradicting_ids = [
            evidence_list[i].id for i in llm_result.contradicting_evidence_indices if 0 <= i < n
        ]

        # Normalise confidence band: low <= mid <= high.
        raw_low = llm_result.confidence_low
        raw_mid = llm_result.confidence_mid
        raw_high = llm_result.confidence_high
        low = min(raw_low, raw_mid, raw_high)
        high = max(raw_low, raw_mid, raw_high)
        mid = max(low, min(raw_mid, high))  # clamp mid into [low, high]

        # Build CollectionGap records and link them to the assessment.
        gaps: list[CollectionGap] = []
        gap_ids: list[str] = []
        for gap_data in llm_result.gaps:
            gap_id = f"gap--{uuid4()}"
            gap_ids.append(gap_id)
            gaps.append(
                CollectionGap(
                    id=gap_id,
                    tenant_id=tenant_id,
                    kiq_id=kiq_id,
                    assessment_id=assessment_id,
                    gap_statement=gap_data.statement,
                    why_needed=gap_data.why_needed,
                    suggested_sources=gap_data.suggested_sources,
                    suggested_plugins=gap_data.suggested_plugins,
                    created=now,
                    modified=now,
                )
            )

        assessment = Assessment(
            id=assessment_id,
            tenant_id=tenant_id,
            kiq_id=kiq_id,
            conclusion=llm_result.conclusion,
            confidence=ConfidenceBand(low=low, mid=mid, high=high),
            reasoning=llm_result.reasoning,
            assumptions=llm_result.assumptions,
            supporting_evidence_ids=supporting_ids,
            contradicting_evidence_ids=contradicting_ids,
            collection_gaps=gap_ids,
            recommended_next_actions=llm_result.recommended_next_actions,
            created=now,
            modified=now,
        )

        return assessment, gaps
