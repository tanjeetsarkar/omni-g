from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior

from src.llm.extractor import LLMExtractor, _LLMEntities, _LLMEntity
from src.models.entities import ExtractionResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_run() -> AsyncMock:
    """Bare AsyncMock representing pydantic_ai Agent run."""
    return AsyncMock()


@pytest.fixture
def extractor(mock_run: AsyncMock) -> Generator[LLMExtractor]:
    """LLMExtractor with pydantic-ai Agent fully mocked (no HTTP calls)."""
    with (
        patch("src.llm.extractor.AsyncOpenAI"),
        patch("src.llm.extractor.Agent.run", new=mock_run),
    ):
        yield LLMExtractor()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_two_entities(extractor: LLMExtractor, mock_run: AsyncMock) -> None:
    """Happy path: mock returns _LLMEntities with 2 generic entities → confidence > 0."""
    entities = [
        _LLMEntity(type="Organization", name="APT28"),
        _LLMEntity(type="Organization", name="APT29"),
    ]
    mock_run.return_value = MagicMock(output=_LLMEntities(entities=entities))

    result = await extractor.extract(
        event_id="evt-001", text="APT28 and APT29 attacked infrastructure"
    )

    assert result.source_event_id == "evt-001"
    assert len(result.entities) == 2
    assert result.extraction_confidence > 0


@pytest.mark.asyncio
async def test_timeout_fallback_returns_result(
    extractor: LLMExtractor, mock_run: AsyncMock
) -> None:
    """Primary raises TimeoutError; fallback succeeds and returns minimal result."""
    entity = _LLMEntity(type="Organization", name="APT28")
    mock_run.side_effect = [
        TimeoutError(),
        MagicMock(output=_LLMEntities(entities=[entity])),
    ]

    result = await extractor.extract(event_id="evt-002", text="APT28 attacked healthcare")

    assert result.source_event_id == "evt-002"
    assert len(result.entities) == 1


@pytest.mark.asyncio
async def test_all_models_fail_returns_empty_result(
    extractor: LLMExtractor, mock_run: AsyncMock
) -> None:
    """Both primary and fallback time out → empty ExtractionResult, no exception raised."""
    mock_run.side_effect = [TimeoutError(), TimeoutError()]

    result = await extractor.extract(event_id="evt-003", text="some text")

    assert result.source_event_id == "evt-003"
    assert result.extraction_confidence == 0.0
    assert result.entities == []


@pytest.mark.asyncio
async def test_instructor_retry_exception_uses_fallback(
    extractor: LLMExtractor, mock_run: AsyncMock
) -> None:
    """Primary UnexpectedModelBehavior is recoverable; fallback still extracts."""
    entity = _LLMEntity(type="Organization", name="APT40")
    mock_run.side_effect = [
        UnexpectedModelBehavior("invalid structured output"),
        MagicMock(output=_LLMEntities(entities=[entity])),
    ]

    result = await extractor.extract(event_id="evt-003a", text="APT40 targeted maritime orgs")

    assert result.source_event_id == "evt-003a"
    assert len(result.entities) == 1


@pytest.mark.asyncio
async def test_non_timeout_llm_errors_degrade_to_empty_result(
    extractor: LLMExtractor, mock_run: AsyncMock
) -> None:
    """Unexpected LLM/transport errors should degrade to an empty result."""
    mock_run.side_effect = [RuntimeError("All connection attempts failed"), RuntimeError("bad")]

    result = await extractor.extract(event_id="evt-003b", text="transport failure case")

    assert result.source_event_id == "evt-003b"
    assert result.extraction_confidence == 0.0
    assert result.entities == []


@pytest.mark.asyncio
async def test_extract_batch_converts_exceptions_to_empty_results(
    extractor: LLMExtractor,
) -> None:
    """extract_batch: one success + one exception → list with empty result for the exception."""

    good = ExtractionResult(
        source_event_id="evt-001",
        entities=[],
        extraction_confidence=0.3,
    )

    call_count = 0

    async def _patched_extract(
        event_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return good
        raise RuntimeError("unexpected LLM failure")

    events = [
        {"id": "evt-001", "text": "APT28 attacked"},
        {"id": "evt-002", "text": "some text"},
    ]
    with patch.object(extractor, "extract", side_effect=_patched_extract):
        results = await extractor.extract_batch(events)

    assert len(results) == 2
    assert results[0].source_event_id == "evt-001"
    assert results[1].source_event_id == "evt-002"
    assert results[1].extraction_confidence == 0.0


@pytest.mark.asyncio
async def test_plugin_metadata_propagated(extractor: LLMExtractor, mock_run: AsyncMock) -> None:
    """plugin_id and plugin_version from metadata are set on the result."""
    mock_run.return_value = MagicMock(output=_LLMEntities())

    result = await extractor.extract(
        event_id="evt-004",
        text="some intelligence text",
        metadata={"plugin_id": "twitter-v1", "plugin_version": "1.2.3"},
    )

    assert result.plugin_id == "twitter-v1"
    assert result.plugin_version == "1.2.3"


@pytest.mark.asyncio
async def test_entity_type_preserved_from_llm(extractor: LLMExtractor, mock_run: AsyncMock) -> None:
    """Entity type string set by the LLM is preserved as-is in the result."""
    entity = _LLMEntity(type="ThreatActor", name="Lazarus Group", confidence=0.9)
    mock_run.return_value = MagicMock(output=_LLMEntities(entities=[entity]))

    result = await extractor.extract(event_id="evt-005", text="Lazarus Group linked to DPRK")

    assert len(result.entities) == 1
    assert result.entities[0].type == "ThreatActor"
    assert result.entities[0].name == "Lazarus Group"
    assert result.entities[0].confidence == 0.9
