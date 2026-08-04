"""Tests for the V2 AssessmentService and assessment models (Step 7)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.dedup.deduplicator import ContentDeduplicator
from src.llm.extractor import LLMExtractor
from src.models.entities import (
    Assessment,
    CollectedEvidence,
    CollectionGap,
    ConfidenceBand,
    CredibilityRating,
    ExtractionResult,
    Hypothesis,
    ReliabilityRating,
    SourceClassification,
)
from src.processor.assessment import AssessmentService, _LLMAssessmentOutput, _LLMGap
from src.processor.pipeline import ASSESSMENTS_PRODUCED, ProcessingPipeline

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
        assertion=f"Entity {i} extracted from source",
        source_timestamp=now,
        source_class=SourceClassification.OPEN_SOURCE_INTELLIGENCE,
        source_reliability=ReliabilityRating.UNKNOWN,
        information_credibility=CredibilityRating.CANNOT_BE_JUDGED,
        extraction_confidence=0.8,
        created=now,
        modified=now,
    )


def _make_llm_output() -> _LLMAssessmentOutput:
    return _LLMAssessmentOutput(
        conclusion="The target organization has expanded into three new markets.",
        confidence_low=0.4,
        confidence_mid=0.6,
        confidence_high=0.8,
        reasoning="Multiple independent sources confirm market entry announcements in Q3.",
        assumptions=["Press releases are accurate.", "No counter-announcements issued."],
        supporting_evidence_indices=[0, 1],
        contradicting_evidence_indices=[],
        gaps=[
            _LLMGap(
                statement="Current financial status of the organization.",
                why_needed="To assess whether expansion is financially sustainable.",
                suggested_sources=["SEC filings", "annual reports"],
                suggested_plugins=["reuters"],
            )
        ],
        recommended_next_actions=["Collect Q4 financial filings.", "Monitor press releases."],
    )


def _counter_value(counter: object, **labels: str) -> float:
    metric = counter.labels(**labels) if labels else counter  # type: ignore[union-attr]
    value_obj = getattr(metric, "_value", None)
    if value_obj is None:
        return 0.0
    return float(value_obj.get())


# ===========================================================================
# ConfidenceBand model tests
# ===========================================================================


class TestConfidenceBand:
    def test_valid_band(self) -> None:
        band = ConfidenceBand(low=0.3, mid=0.6, high=0.8)
        assert band.low == 0.3
        assert band.mid == 0.6
        assert band.high == 0.8

    def test_all_equal_is_valid(self) -> None:
        band = ConfidenceBand(low=0.5, mid=0.5, high=0.5)
        assert band.low == band.mid == band.high == 0.5

    def test_low_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConfidenceBand(low=-0.1, mid=0.5, high=0.8)

    def test_high_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConfidenceBand(low=0.3, mid=0.5, high=1.1)

    def test_mid_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            ConfidenceBand(low=0.3, mid=1.2, high=1.5)


# ===========================================================================
# Hypothesis model tests
# ===========================================================================


class TestHypothesis:
    def test_defaults(self) -> None:
        now = _now()
        h = Hypothesis(
            id="hypothesis--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            statement="The org is planning an acquisition.",
            reasoning="Based on financial signals.",
            created=now,
            modified=now,
        )
        assert h.status == "CANDIDATE"
        assert h.confidence == 0.0
        assert h.generated_by == "LLM"
        assert h.supporting_evidence_ids == []
        assert h.contradicting_evidence_ids == []
        assert h.likelihood_ratio is None
        assert h.analyst_notes is None

    def test_custom_status(self) -> None:
        now = _now()
        h = Hypothesis(
            id="hypothesis--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            statement="Org is not planning an acquisition.",
            reasoning="No financial signals.",
            status="REJECTED",
            created=now,
            modified=now,
        )
        assert h.status == "REJECTED"

    def test_confidence_bounds(self) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            Hypothesis(
                id="h--x",
                tenant_id="t1",
                kiq_id="k--x",
                statement="s",
                reasoning="r",
                confidence=1.5,
                created=now,
                modified=now,
            )

    def test_evidence_linkage(self) -> None:
        now = _now()
        h = Hypothesis(
            id="hypothesis--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            statement="Statement.",
            reasoning="Reasoning.",
            supporting_evidence_ids=["evidence--aaa"],
            contradicting_evidence_ids=["evidence--bbb"],
            created=now,
            modified=now,
        )
        assert "evidence--aaa" in h.supporting_evidence_ids
        assert "evidence--bbb" in h.contradicting_evidence_ids


# ===========================================================================
# Assessment model tests
# ===========================================================================


class TestAssessmentModel:
    def test_defaults(self) -> None:
        now = _now()
        a = Assessment(
            id="assessment--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            conclusion="The target is expanding operations.",
            confidence=ConfidenceBand(low=0.4, mid=0.6, high=0.8),
            reasoning="Multiple corroborating sources.",
            created=now,
            modified=now,
        )
        assert a.status == "DRAFT"
        assert a.produced_by == "PROCESSOR"
        assert a.version == 1
        assert a.supporting_evidence_ids == []
        assert a.contradicting_evidence_ids == []
        assert a.collection_gaps == []
        assert a.recommended_next_actions == []
        assert a.hypothesis_id is None
        assert a.superseded_by_id is None

    def test_evidence_ids_stored(self) -> None:
        now = _now()
        a = Assessment(
            id="assessment--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            conclusion="Conclusion.",
            confidence=ConfidenceBand(low=0.3, mid=0.5, high=0.7),
            reasoning="Reasoning.",
            supporting_evidence_ids=["evidence--aaa", "evidence--bbb"],
            contradicting_evidence_ids=["evidence--ccc"],
            created=now,
            modified=now,
        )
        assert len(a.supporting_evidence_ids) == 2
        assert len(a.contradicting_evidence_ids) == 1

    def test_gap_ids_stored(self) -> None:
        now = _now()
        a = Assessment(
            id="assessment--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            conclusion="Conclusion.",
            confidence=ConfidenceBand(low=0.2, mid=0.4, high=0.6),
            reasoning="Reasoning.",
            collection_gaps=["gap--aaa", "gap--bbb"],
            created=now,
            modified=now,
        )
        assert "gap--aaa" in a.collection_gaps
        assert "gap--bbb" in a.collection_gaps


# ===========================================================================
# CollectionGap model tests
# ===========================================================================


class TestCollectionGapModel:
    def test_defaults(self) -> None:
        now = _now()
        gap = CollectionGap(
            id="gap--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            gap_statement="Current financial status.",
            why_needed="To assess acquisition financing.",
            created=now,
            modified=now,
        )
        assert gap.status == "IDENTIFIED"
        assert gap.tasking_issued is False
        assert gap.collection_priority == 0
        assert gap.suggested_sources == []
        assert gap.suggested_plugins == []
        assert gap.assessment_id is None

    def test_assessment_linkage(self) -> None:
        now = _now()
        gap = CollectionGap(
            id="gap--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            assessment_id="assessment--test",
            gap_statement="Statement.",
            why_needed="Why.",
            created=now,
            modified=now,
        )
        assert gap.assessment_id == "assessment--test"

    def test_tasking_and_priority(self) -> None:
        now = _now()
        gap = CollectionGap(
            id="gap--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            gap_statement="Statement.",
            why_needed="Why.",
            tasking_issued=True,
            collection_priority=5,
            status="TASKED",
            created=now,
            modified=now,
        )
        assert gap.tasking_issued is True
        assert gap.collection_priority == 5
        assert gap.status == "TASKED"


# ===========================================================================
# ExtractionResult carries assessment
# ===========================================================================


class TestExtractionResultAssessment:
    def test_assessment_defaults_to_none(self) -> None:
        result = ExtractionResult(source_event_id="ev-1")
        assert result.assessment is None

    def test_assessment_accepted(self) -> None:
        now = _now()
        a = Assessment(
            id="assessment--test",
            tenant_id="t1",
            kiq_id="kiq--test",
            conclusion="Conclusion.",
            confidence=ConfidenceBand(low=0.3, mid=0.5, high=0.7),
            reasoning="Reasoning.",
            created=now,
            modified=now,
        )
        result = ExtractionResult(source_event_id="ev-1", assessment=a)
        assert result.assessment is not None
        assert result.assessment.id == "assessment--test"


# ===========================================================================
# AssessmentService unit tests
# ===========================================================================


class TestAssessmentService:
    @pytest.fixture()
    def service(self) -> AssessmentService:
        return AssessmentService()

    async def test_returns_none_for_empty_evidence(self, service: AssessmentService) -> None:
        result = await service.generate("kiq--test", "tenant1", [])
        assert result is None

    async def test_degenerate_assessment_structure(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(i) for i in range(3)]
        degenerate = service._degenerate_assessment(evidence)
        assert degenerate.conclusion
        assert 0.0 <= degenerate.confidence_low <= degenerate.confidence_mid
        assert degenerate.confidence_mid <= degenerate.confidence_high <= 1.0
        assert len(degenerate.gaps) >= 1

    async def test_degenerate_confidence_scales_with_extraction_confidence(
        self, service: AssessmentService
    ) -> None:
        evidence = [_make_evidence(0)]
        evidence[0] = evidence[0].model_copy(update={"extraction_confidence": 0.9})
        degenerate = service._degenerate_assessment(evidence)
        assert degenerate.confidence_mid == pytest.approx(0.9, abs=0.01)

    async def test_generate_with_mocked_llm(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(0), _make_evidence(1)]
        llm_output = _make_llm_output()

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, gaps = result
        assert assessment.kiq_id == "kiq--test"
        assert assessment.tenant_id == "tenant1"
        assert assessment.id.startswith("assessment--")
        assert assessment.conclusion == llm_output.conclusion
        assert assessment.confidence.low <= assessment.confidence.mid <= assessment.confidence.high
        assert len(gaps) == 1
        assert gaps[0].kiq_id == "kiq--test"
        assert gaps[0].assessment_id == assessment.id
        assert gaps[0].id.startswith("gap--")
        assert "SEC filings" in gaps[0].suggested_sources
        assert "reuters" in gaps[0].suggested_plugins

    async def test_generate_uses_degenerate_on_llm_failure(
        self, service: AssessmentService
    ) -> None:
        evidence = [_make_evidence(0)]

        with patch.object(service, "_call_llm", new=AsyncMock(side_effect=Exception("LLM down"))):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, gaps = result
        assert assessment.kiq_id == "kiq--test"
        assert (
            "fallback" in assessment.conclusion.lower()
            or "rule-based" in assessment.conclusion.lower()
        )
        assert len(gaps) >= 1

    async def test_generate_supporting_evidence_ids_resolved(
        self, service: AssessmentService
    ) -> None:
        evidence = [_make_evidence(i) for i in range(3)]
        llm_output = _make_llm_output()
        llm_output.supporting_evidence_indices = [0, 2]
        llm_output.contradicting_evidence_indices = [1]

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, _ = result
        assert evidence[0].id in assessment.supporting_evidence_ids
        assert evidence[2].id in assessment.supporting_evidence_ids
        assert evidence[1].id in assessment.contradicting_evidence_ids

    async def test_generate_out_of_range_indices_ignored(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output()
        llm_output.supporting_evidence_indices = [0, 99, -1]  # 99 and -1 are out of range

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, _ = result
        assert evidence[0].id in assessment.supporting_evidence_ids
        assert len(assessment.supporting_evidence_ids) == 1  # only index 0 is valid

    async def test_generate_no_gaps_yields_empty_gap_list(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output()
        llm_output.gaps = []

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, gaps = result
        assert gaps == []
        assert assessment.collection_gaps == []

    async def test_confidence_band_normalised_low_le_mid_le_high(
        self, service: AssessmentService
    ) -> None:
        """Service normalises inverted LLM confidence values so low <= mid <= high."""
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output()
        # Deliberately invert order
        llm_output.confidence_low = 0.8
        llm_output.confidence_mid = 0.5
        llm_output.confidence_high = 0.3

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, _ = result
        assert assessment.confidence.low <= assessment.confidence.mid <= assessment.confidence.high

    async def test_assessment_next_actions_preserved(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output()
        llm_output.recommended_next_actions = ["Action A", "Action B"]

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, _ = result
        assert "Action A" in assessment.recommended_next_actions
        assert "Action B" in assessment.recommended_next_actions

    async def test_assessment_assumptions_preserved(self, service: AssessmentService) -> None:
        evidence = [_make_evidence(0)]
        llm_output = _make_llm_output()
        llm_output.assumptions = ["Assumption X"]

        with patch.object(service, "_call_llm", new=AsyncMock(return_value=llm_output)):
            result = await service.generate("kiq--test", "tenant1", evidence)

        assert result is not None
        assessment, _ = result
        assert "Assumption X" in assessment.assumptions


# ===========================================================================
# Pipeline integration tests
# ===========================================================================


class TestPipelineAssessmentIntegration:
    @pytest.fixture()
    def mock_extractor(self) -> AsyncMock:
        from datetime import UTC, datetime

        from src.models.entities import Entity, EvidenceSpan

        now = datetime.now(UTC)
        # Entity name "Intel" appears in the payload text "Tasked intel feed text"
        # so it passes the grounding gate (case-insensitive substring match).
        entity = Entity(
            id="entity--00000000-0000-0000-0000-000000000001",
            type="Organization",
            name="Intel",
            source_spans=[EvidenceSpan(text="intel")],
            created=now,
            modified=now,
        )
        mock = AsyncMock()
        mock.extract.return_value = ExtractionResult(
            source_event_id="evt-assess",
            entities=[entity],
            relationships=[],
            extraction_confidence=0.75,
        )
        return mock

    @pytest.fixture()
    def mock_assessment_service(self) -> AsyncMock:
        mock = AsyncMock(spec=AssessmentService)
        now = _now()
        assessment = Assessment(
            id="assessment--pipeline-test",
            tenant_id="tenant1",
            kiq_id="kiq--abc",
            conclusion="Pipeline assessment test conclusion.",
            confidence=ConfidenceBand(low=0.4, mid=0.6, high=0.8),
            reasoning="Test reasoning.",
            created=now,
            modified=now,
        )
        mock.generate.return_value = (assessment, [])
        return mock

    async def test_assessment_generated_for_kiq_tagged_event(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: AsyncMock,
        mock_assessment_service: AsyncMock,
    ) -> None:
        """Pipeline generates an assessment when kiq_id is set and evidence exists."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            extractor=cast(LLMExtractor, mock_extractor),
            assessment_service=cast(AssessmentService, mock_assessment_service),
        )
        event = {
            "id": "evt-kiq-assess",
            "tenant_id": "tenant1",
            "payload": {"text": "Tasked intel feed text"},
            "kiq_id": "kiq--abc",
        }
        result = await pipeline.process(event)
        assert result is not None
        mock_assessment_service.generate.assert_called_once()
        call_kwargs = mock_assessment_service.generate.call_args
        assert call_kwargs.kwargs["kiq_id"] == "kiq--abc"
        assert call_kwargs.kwargs["tenant_id"] == "tenant1"

    async def test_assessment_not_generated_for_untasked_event(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: AsyncMock,
        mock_assessment_service: AsyncMock,
    ) -> None:
        """Pipeline skips assessment generation when kiq_id is absent."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            extractor=cast(LLMExtractor, mock_extractor),
            assessment_service=cast(AssessmentService, mock_assessment_service),
        )
        event = {
            "id": "evt-untasked-assess",
            "tenant_id": "tenant1",
            "payload": {"text": "Untasked general feed"},
        }
        result = await pipeline.process(event)
        assert result is not None
        mock_assessment_service.generate.assert_not_called()

    async def test_assessment_stored_in_extraction_result(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: AsyncMock,
        mock_assessment_service: AsyncMock,
    ) -> None:
        """ExtractionResult.assessment is populated when assessment_service is wired."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            extractor=cast(LLMExtractor, mock_extractor),
            assessment_service=cast(AssessmentService, mock_assessment_service),
        )
        event = {
            "id": "evt-store-assess",
            "tenant_id": "tenant1",
            "payload": {"text": "Tasked intel text"},
            "kiq_id": "kiq--abc",
        }
        result = await pipeline.process(event)
        assert result is not None
        assert result.assessment is not None
        assert result.assessment.id == "assessment--pipeline-test"
        assert result.assessment.kiq_id == "kiq--abc"

    async def test_assessment_counter_incremented(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: AsyncMock,
        mock_assessment_service: AsyncMock,
    ) -> None:
        """ASSESSMENTS_PRODUCED counter increments when an assessment is produced."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            extractor=cast(LLMExtractor, mock_extractor),
            assessment_service=cast(AssessmentService, mock_assessment_service),
        )
        before = _counter_value(ASSESSMENTS_PRODUCED, tenant_id="tenant1")
        event = {
            "id": "evt-counter-assess",
            "tenant_id": "tenant1",
            "payload": {"text": "Tasked intel text for counter"},
            "kiq_id": "kiq--abc",
        }
        await pipeline.process(event)
        assert _counter_value(ASSESSMENTS_PRODUCED, tenant_id="tenant1") == before + 1

    async def test_pipeline_without_assessment_service_still_works(
        self,
        fake_deduplicator: ContentDeduplicator,
        mock_extractor: AsyncMock,
    ) -> None:
        """Pipeline completes normally when no assessment_service is wired in."""
        pipeline = ProcessingPipeline(
            deduplicator=fake_deduplicator,
            extractor=cast(LLMExtractor, mock_extractor),
        )
        event = {
            "id": "evt-no-assess",
            "tenant_id": "tenant1",
            "payload": {"text": "KIQ-tagged event without assessment service"},
            "kiq_id": "kiq--no-service",
        }
        result = await pipeline.process(event)
        assert result is not None
        assert result.assessment is None
