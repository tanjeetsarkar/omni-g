"""V2 Step 9 — Competing Hypothesis generation and ACH scoring.

Generates 2–4 competing hypotheses for a KIQ from collected evidence using the
same LLM endpoint as the assessment service. After generation, applies a
lightweight Analysis of Competing Hypotheses (ACH) scoring pass to rank
candidates and surface the leading hypothesis.

Used by:
- ProcessingPipeline (hot-path: generate candidates + ACH score)
- reanalyze_kiq_task (Celery background: full re-analysis with updated assessment)
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

from ..models.entities import CollectedEvidence, Hypothesis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM configuration — mirrors extractor.py and assessment.py
# ---------------------------------------------------------------------------

_ollama_url = os.getenv("OLLAMA_URL")
LLM_BASE_URL: str = os.getenv(
    "LLM_BASE_URL",
    f"{_ollama_url.rstrip('/')}/v1" if _ollama_url else "http://localhost:11434/v1",
)
LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"))

_HYPOTHESIS_SYSTEM_PROMPT = """\
You are an intelligence analyst applying Analysis of Competing Hypotheses (ACH).
Given a Key Intelligence Question (KIQ) ID and a numbered list of collected evidence, \
generate 2 to 4 competing hypotheses that could explain the evidence.

Hypothesis generation rules:
- Each hypothesis must be a distinct, declarative explanation of what the evidence suggests.
- Hypotheses should represent meaningfully different explanations — avoid near-duplicates.
- Include a brief reasoning (1-3 sentences) explaining why the hypothesis is plausible.
- For each hypothesis, identify which evidence indices (0-based) SUPPORT it and which CONTRADICT it.
- Order hypotheses from most to least plausible given the weight of evidence.

STRUCTURAL RULES:
- Return exactly 2 to 4 hypotheses. Never fewer than 2, never more than 4.
- statement must be a single non-empty declarative sentence.
- reasoning must be a non-empty string of at least one sentence.
- supporting_evidence_indices and contradicting_evidence_indices are 0-based integers \
  referencing the input evidence list.
- The same evidence index may appear in both lists for different hypotheses.
"""


# ---------------------------------------------------------------------------
# Internal LLM output models
# ---------------------------------------------------------------------------


class _LLMHypothesis(BaseModel):
    """Single hypothesis produced by the LLM."""

    statement: str
    reasoning: str
    supporting_evidence_indices: list[int] = Field(default_factory=list)
    contradicting_evidence_indices: list[int] = Field(default_factory=list)


class _LLMHypothesesOutput(BaseModel):
    """Top-level structured output from the hypothesis generation LLM call."""

    hypotheses: list[_LLMHypothesis] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# HypothesisService
# ---------------------------------------------------------------------------


class HypothesisService:
    """Generates and scores competing hypotheses for a KIQ (ACH workflow).

    Called by :class:`~src.processor.pipeline.ProcessingPipeline` after
    evidence creation (step 3.6) when a ``kiq_id`` is present. Produces 2–4
    :class:`~src.models.entities.Hypothesis` objects, scores them via an
    Analysis of Competing Hypotheses (ACH) likelihood-ratio pass, and returns
    them sorted by descending confidence.

    The first element in the returned list is the LEADING hypothesis and is
    passed directly to :class:`~src.processor.assessment.AssessmentService` so
    the produced :class:`~src.models.entities.Assessment` carries an explicit
    ``hypothesis_id`` reference.

    On LLM failure the service returns two degenerate CANDIDATE hypotheses so
    the pipeline always has output when evidence is present.
    """

    def __init__(self) -> None:
        self._openai_client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
        self._provider = OpenAIProvider(openai_client=self._openai_client)
        self._model = OpenAIChatModel(LLM_MODEL, provider=self._provider)

    async def generate_candidates(
        self,
        kiq_id: str,
        tenant_id: str,
        evidence_list: list[CollectedEvidence],
    ) -> list[Hypothesis]:
        """Generate and ACH-score 2–4 competing hypotheses from evidence.

        Returns :class:`~src.models.entities.Hypothesis` objects sorted by
        descending confidence (LEADING first).  Returns an empty list when
        ``evidence_list`` is empty.  Returns two degenerate CANDIDATE hypotheses
        on LLM failure so downstream assessment generation always has a leading
        hypothesis to reference.
        """
        if not evidence_list:
            return []

        evidence_summary = self._build_evidence_summary(evidence_list)
        user_prompt = (
            f"KIQ ID: {kiq_id}\n"
            f"Evidence count: {len(evidence_list)}\n\n"
            f"Evidence:\n{evidence_summary}"
        )

        try:
            llm_output = await self._call_llm(user_prompt)
        except Exception as exc:
            logger.warning(
                "hypothesis_llm_failed",
                extra={"kiq_id": kiq_id, "error_type": type(exc).__name__, "error": str(exc)},
            )
            llm_output = self._degenerate_output(evidence_list)

        hypotheses = self._build_hypotheses(kiq_id, tenant_id, evidence_list, llm_output)
        return self.score_hypotheses(hypotheses, evidence_list)

    def score_hypotheses(
        self,
        hypotheses: list[Hypothesis],
        evidence_list: list[CollectedEvidence],  # reserved: future evidence-weight scoring
    ) -> list[Hypothesis]:
        """Apply ACH scoring to rank hypotheses by confidence.

        Computes a likelihood ratio for each hypothesis from the count of
        supporting vs contradicting evidence IDs already bound to the object:
        ``ratio = (|supporting| + 1) / (|contradicting| + 1)``

        Normalises confidence so all scores sum to 1.0, sorts descending, and
        assigns status labels by rank: LEADING (0) > PROBABLE (1) > PLAUSIBLE
        (2) > CANDIDATE (3+).
        """
        if not hypotheses:
            return []

        raw: list[float] = []
        for h in hypotheses:
            s = len(h.supporting_evidence_ids)
            c = len(h.contradicting_evidence_ids)
            raw.append((s + 1.0) / (c + 1.0))

        total = sum(raw) or 1.0

        scored: list[Hypothesis] = []
        for h, r in zip(hypotheses, raw, strict=True):
            scored.append(
                h.model_copy(
                    update={
                        "likelihood_ratio": round(r, 4),
                        "confidence": round(r / total, 4),
                        "modified": datetime.now(UTC),
                    }
                )
            )

        scored.sort(key=lambda h: h.confidence, reverse=True)

        _STATUSES = ("LEADING", "PROBABLE", "PLAUSIBLE", "CANDIDATE")
        return [
            h.model_copy(update={"status": _STATUSES[min(i, len(_STATUSES) - 1)]})
            for i, h in enumerate(scored)
        ]

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

    async def _call_llm(self, user_prompt: str) -> _LLMHypothesesOutput:
        agent: Agent[None, _LLMHypothesesOutput] = Agent(
            self._model,
            system_prompt=_HYPOTHESIS_SYSTEM_PROMPT,
            output_type=_LLMHypothesesOutput,
            retries=2,
        )
        run_res = await agent.run(user_prompt)
        return run_res.output

    def _degenerate_output(self, evidence_list: list[CollectedEvidence]) -> _LLMHypothesesOutput:
        """Rule-based fallback: two hypotheses when LLM is unavailable."""
        n = len(evidence_list)
        return _LLMHypothesesOutput(
            hypotheses=[
                _LLMHypothesis(
                    statement=(
                        f"Entities and relationships in {n} evidence item(s) are directly "
                        "relevant to the KIQ (LLM unavailable; rule-based fallback)."
                    ),
                    reasoning=(
                        f"{n} evidence item(s) were extracted and scored. "
                        "Insufficient LLM capacity to generate competing explanations."
                    ),
                    supporting_evidence_indices=list(range(min(n, 3))),
                    contradicting_evidence_indices=[],
                ),
                _LLMHypothesis(
                    statement=(
                        "The KIQ cannot be answered with current evidence alone "
                        "(alternative fallback hypothesis)."
                    ),
                    reasoning=(
                        "Evidence coverage may be insufficient to rule out alternative "
                        "explanations without additional collection."
                    ),
                    supporting_evidence_indices=[],
                    contradicting_evidence_indices=list(range(min(n, 3))),
                ),
            ]
        )

    def _build_hypotheses(
        self,
        kiq_id: str,
        tenant_id: str,
        evidence_list: list[CollectedEvidence],
        llm_output: _LLMHypothesesOutput,
    ) -> list[Hypothesis]:
        """Convert LLM output to :class:`~src.models.entities.Hypothesis` objects."""
        n = len(evidence_list)
        now = datetime.now(UTC)
        result: list[Hypothesis] = []
        for llm_h in llm_output.hypotheses:
            supporting_ids = [
                evidence_list[i].id for i in llm_h.supporting_evidence_indices if 0 <= i < n
            ]
            contradicting_ids = [
                evidence_list[i].id for i in llm_h.contradicting_evidence_indices if 0 <= i < n
            ]
            result.append(
                Hypothesis(
                    id=f"hypothesis--{uuid4()}",
                    tenant_id=tenant_id,
                    kiq_id=kiq_id,
                    statement=llm_h.statement,
                    reasoning=llm_h.reasoning,
                    supporting_evidence_ids=supporting_ids,
                    contradicting_evidence_ids=contradicting_ids,
                    status="CANDIDATE",  # updated by score_hypotheses
                    confidence=0.0,  # updated by score_hypotheses
                    generated_by="LLM",
                    created=now,
                    modified=now,
                )
            )
        return result
