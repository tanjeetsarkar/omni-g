"""Tests for V2 Step 9: HypothesisService and pipeline hypothesis integration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.entities import (
    CollectedEvidence,
    CredibilityRating,
    ExtractionResult,
    Hypothesis,
    ReliabilityRating,
    SourceClassification,
)
from src.processor.hypothesis import (
    HypothesisService,
    _LLMHypothesesOutput,
    _LLMHypothesis,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_evidence(i: int = 0, *, kiq_id: str | None = "kiq--test") -> CollectedEvidence:
    now = _now()
    return CollectedEvidence(
        id=f"evidence--{i:08x}-0000-0000-0000-000000000000",
        tenant_id="tenant1",
        kiq_id=kiq_id,
        source_event_id=f"event--{i:08x}",
        entity_id=f"entity--{i:08x}-0000-0000-0000-000000000000",
        assertion=f"Entity {i} extracted from source event {i}",
        source_timestamp=now,
        source_class=SourceClassification.OPEN_SOURCE_INTELLIGENCE,
        source_reliability=ReliabilityRating.UNKNOWN,
        information_credibility=CredibilityRating.CANNOT_BE_JUDGED,
        extraction_confidence=0.8,
        created=now,
        modified=now,
    )


def _make_llm_output(num_hypotheses: int = 3) -> _LLMHypothesesOutput:
    hypotheses = [
        _LLMHypothesis(
            statement=f"Hypothesis {i}: The target organization has taken action {i}.",
            reasoning=f"Evidence {i} points to action {i} being likely.",
            supporting_evidence_indices=[i % 3],
            contradicting_evidence_indices=[(i + 1) % 3] if i < 2 else [],
        )
        for i in range(num_hypotheses)
    ]
    return _LLMHypothesesOutput(hypotheses=hypotheses)


# ---------------------------------------------------------------------------
# HypothesisService.score_hypotheses tests
# ---------------------------------------------------------------------------


class TestScoreHypotheses:
    def _make_bare_hypothesis(
        self,
        *,
        supporting: list[str],
        contradicting: list[str],
    ) -> Hypothesis:
        now = _now()
        return Hypothesis(
            id="hypothesis--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            statement="Test hypothesis.",
            reasoning="Test reasoning.",
            supporting_evidence_ids=supporting,
            contradicting_evidence_ids=contradicting,
            created=now,
            modified=now,
        )

    def test_empty_input_returns_empty(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        result = svc.score_hypotheses([], [])
        assert result == []

    def test_sorts_by_confidence_descending(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        # h_strong has 3 supporting, 0 contradicting → high ratio
        h_strong = self._make_bare_hypothesis(supporting=["ev1", "ev2", "ev3"], contradicting=[])
        # h_weak has 0 supporting, 2 contradicting → low ratio
        h_weak = self._make_bare_hypothesis(supporting=[], contradicting=["ev1", "ev2"])
        result = svc.score_hypotheses([h_weak, h_strong], [])
        assert result[0].confidence > result[1].confidence

    def test_leading_hypothesis_has_status_leading(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        h_strong = self._make_bare_hypothesis(supporting=["ev1", "ev2"], contradicting=[])
        h_weak = self._make_bare_hypothesis(supporting=[], contradicting=["ev1"])
        result = svc.score_hypotheses([h_weak, h_strong], [])
        assert result[0].status == "LEADING"

    def test_status_labels_by_rank(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        now = _now()
        hypotheses = [
            Hypothesis(
                id=f"hypothesis--{i:08x}-0000-0000-0000-000000000000",
                tenant_id="t1",
                kiq_id="kiq--test",
                statement=f"H{i}",
                reasoning="r",
                supporting_evidence_ids=["ev"] * (4 - i),  # decreasing support
                contradicting_evidence_ids=[],
                created=now,
                modified=now,
            )
            for i in range(4)
        ]
        result = svc.score_hypotheses(hypotheses, [])
        assert result[0].status == "LEADING"
        assert result[1].status == "PROBABLE"
        assert result[2].status == "PLAUSIBLE"
        assert result[3].status == "CANDIDATE"

    def test_confidence_sums_to_one(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        now = _now()
        hypotheses = [
            Hypothesis(
                id=f"hypothesis--{i:08x}-0000-0000-0000-000000000000",
                tenant_id="t1",
                kiq_id="kiq--test",
                statement=f"H{i}",
                reasoning="r",
                supporting_evidence_ids=["ev"] * i,
                contradicting_evidence_ids=[],
                created=now,
                modified=now,
            )
            for i in range(3)
        ]
        result = svc.score_hypotheses(hypotheses, [])
        total = sum(h.confidence for h in result)
        assert abs(total - 1.0) < 1e-6

    def test_likelihood_ratio_set(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        h = self._make_bare_hypothesis(supporting=["ev1", "ev2"], contradicting=["ev3"])
        result = svc.score_hypotheses([h], [])
        # (2+1)/(1+1) = 1.5
        assert result[0].likelihood_ratio == pytest.approx(1.5, abs=1e-4)

    def test_single_hypothesis_gets_leading_status(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        h = self._make_bare_hypothesis(supporting=[], contradicting=[])
        result = svc.score_hypotheses([h], [])
        assert len(result) == 1
        assert result[0].status == "LEADING"
        assert result[0].confidence == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# HypothesisService.generate_candidates tests
# ---------------------------------------------------------------------------


class TestGenerateCandidates:
    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_evidence(self) -> None:
        svc = HypothesisService.__new__(HypothesisService)
        result = await svc.generate_candidates("kiq--test", "t1", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_output_produces_hypotheses(self) -> None:
        evidence = [_make_evidence(i) for i in range(3)]
        llm_output = _make_llm_output(num_hypotheses=3)

        async def mock_run(user_prompt: str) -> MagicMock:
            m = MagicMock()
            m.output = llm_output
            return m

        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(output=llm_output))
            result = await svc.generate_candidates("kiq--test", "tenant1", evidence)

        assert len(result) == 3
        # Leading hypothesis first
        assert result[0].status == "LEADING"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_degenerate_fallback(self) -> None:
        evidence = [_make_evidence(i) for i in range(2)]
        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
            result = await svc.generate_candidates("kiq--test", "tenant1", evidence)

        # Degenerate fallback always returns exactly 2 hypotheses
        assert len(result) == 2
        assert result[0].status == "LEADING"
        assert all(h.kiq_id == "kiq--test" for h in result)

    @pytest.mark.asyncio
    async def test_hypotheses_carry_kiq_and_tenant(self) -> None:
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output(num_hypotheses=2)
        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(output=llm_output))
            result = await svc.generate_candidates("kiq--abc", "tenant-xyz", evidence)

        for h in result:
            assert h.kiq_id == "kiq--abc"
            assert h.tenant_id == "tenant-xyz"

    @pytest.mark.asyncio
    async def test_evidence_ids_bound_correctly(self) -> None:
        evidence = [_make_evidence(i) for i in range(3)]
        # First hypothesis supports evidence[0], contradicts evidence[1]
        llm_output = _LLMHypothesesOutput(
            hypotheses=[
                _LLMHypothesis(
                    statement="H1",
                    reasoning="r1",
                    supporting_evidence_indices=[0],
                    contradicting_evidence_indices=[1],
                ),
                _LLMHypothesis(
                    statement="H2",
                    reasoning="r2",
                    supporting_evidence_indices=[2],
                    contradicting_evidence_indices=[],
                ),
            ]
        )
        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(output=llm_output))
            result = await svc.generate_candidates("kiq--test", "t1", evidence)

        # Find the hypothesis for H1 or H2 by statement
        h_by_statement = {h.statement: h for h in result}
        h1 = h_by_statement["H1"]
        assert evidence[0].id in h1.supporting_evidence_ids
        assert evidence[1].id in h1.contradicting_evidence_ids

    @pytest.mark.asyncio
    async def test_out_of_range_evidence_indices_silently_skipped(self) -> None:
        evidence = [_make_evidence(0)]  # Only 1 item; index 5 is out of range
        llm_output = _LLMHypothesesOutput(
            hypotheses=[
                _LLMHypothesis(
                    statement="H1",
                    reasoning="r1",
                    supporting_evidence_indices=[0, 5, 99],  # 5 and 99 are OOB
                    contradicting_evidence_indices=[],
                ),
                _LLMHypothesis(
                    statement="H2",
                    reasoning="r2",
                    supporting_evidence_indices=[],
                    contradicting_evidence_indices=[],
                ),
            ]
        )
        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(output=llm_output))
            result = await svc.generate_candidates("kiq--test", "t1", evidence)

        h_by_statement = {h.statement: h for h in result}
        h1 = h_by_statement["H1"]
        # Only evidence[0].id should be in supporting; OOB indices silently dropped
        assert len(h1.supporting_evidence_ids) == 1
        assert evidence[0].id in h1.supporting_evidence_ids


# ---------------------------------------------------------------------------
# Multiple hypotheses per KIQ — Step 9 acceptance criterion
# ---------------------------------------------------------------------------


class TestMultipleHypothesesPerKiq:
    @pytest.mark.asyncio
    async def test_more_than_one_hypothesis_for_same_kiq(self) -> None:
        """Verify multiple distinct hypotheses can exist for the same KIQ."""
        evidence = [_make_evidence(i) for i in range(4)]
        llm_output = _make_llm_output(num_hypotheses=4)
        svc = HypothesisService.__new__(HypothesisService)
        svc._model = MagicMock()

        with patch("src.processor.hypothesis.Agent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(output=llm_output))
            result = await svc.generate_candidates("kiq--shared", "t1", evidence)

        assert len(result) >= 2
        kiq_ids = {h.kiq_id for h in result}
        assert kiq_ids == {"kiq--shared"}

    def test_hypotheses_have_unique_ids(self) -> None:
        """Each Hypothesis object carries a distinct id."""
        svc = HypothesisService.__new__(HypothesisService)
        evidence = [_make_evidence(i) for i in range(2)]
        degenerate = svc._degenerate_output(evidence)
        hypotheses = svc._build_hypotheses("kiq--x", "t1", evidence, degenerate)
        ids = [h.id for h in hypotheses]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# reanalyze_kiq_task integration — Step 9 acceptance criterion
# ---------------------------------------------------------------------------


class TestReanalyzeKiqTask:
    def test_run_reanalyze_kiq_returns_completed(self) -> None:
        """_run_reanalyze_kiq returns completed status when hypotheses are generated."""
        from src.processor import tasks as processor_tasks

        evidence_payload = [_make_evidence(i).model_dump(mode="json") for i in range(2)]

        async def mock_generate_candidates(
            kiq_id: str, tenant_id: str, evidence_list: Any
        ) -> list[Hypothesis]:
            now = _now()
            return [
                Hypothesis(
                    id=f"hypothesis--{i:08x}-0000-0000-0000-000000000000",
                    tenant_id=tenant_id,
                    kiq_id=kiq_id,
                    statement=f"Hypothesis {i}",
                    reasoning="r",
                    status="LEADING" if i == 0 else "PROBABLE",
                    confidence=0.7 if i == 0 else 0.3,
                    created=now,
                    modified=now,
                )
                for i in range(2)
            ]

        from src.models.entities import Assessment, CollectionGap, ConfidenceBand

        async def mock_assessment_generate(
            kiq_id: str,
            tenant_id: str,
            evidence_list: Any,
            leading_hypothesis: Any = None,
        ) -> tuple[Assessment, list[CollectionGap]]:
            now = _now()
            assessment = Assessment(
                id="assessment--test",
                tenant_id=tenant_id,
                kiq_id=kiq_id,
                hypothesis_id=leading_hypothesis.id if leading_hypothesis else None,
                conclusion="Test conclusion.",
                confidence=ConfidenceBand(low=0.4, mid=0.6, high=0.8),
                reasoning="Test reasoning.",
                created=now,
                modified=now,
            )
            return assessment, []

        with (
            patch(
                "src.processor.hypothesis.HypothesisService",
                autospec=True,
            ) as MockHypSvc,
            patch(
                "src.processor.assessment.AssessmentService",
                autospec=True,
            ) as MockAsmtSvc,
        ):
            MockHypSvc.return_value.generate_candidates = mock_generate_candidates
            MockAsmtSvc.return_value.generate = mock_assessment_generate

            result = processor_tasks._run_reanalyze_kiq("kiq--bg-test", "tenant1", evidence_payload)

        assert result["status"] == "completed"
        assert result["kiq_id"] == "kiq--bg-test"
        assert result["hypotheses_count"] == 2
        assert "assessment_id" in result

    def test_run_reanalyze_kiq_skipped_when_no_evidence(self) -> None:
        """_run_reanalyze_kiq returns skipped when evidence_payload is empty."""
        from src.processor import tasks as processor_tasks

        result = processor_tasks._run_reanalyze_kiq("kiq--empty", "t1", [])
        assert result["status"] == "skipped"
        assert result["reason"] == "no_evidence"


# ---------------------------------------------------------------------------
# ExtractionResult.hypotheses field — Step 9 schema test
# ---------------------------------------------------------------------------


class TestExtractionResultHypotheses:
    def test_hypotheses_field_defaults_empty(self) -> None:
        result = ExtractionResult(source_event_id="ev--test")
        assert result.hypotheses == []

    def test_hypotheses_field_accepts_list(self) -> None:
        now = _now()
        h = Hypothesis(
            id="hypothesis--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            statement="Test.",
            reasoning="r",
            created=now,
            modified=now,
        )
        result = ExtractionResult(source_event_id="ev--test", hypotheses=[h])
        assert len(result.hypotheses) == 1
        assert result.hypotheses[0].id == "hypothesis--test"
