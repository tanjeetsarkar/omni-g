from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.extractor import LLMExtractor, _LLMEntities
from src.models.stix import ExtractionResult, ThreatActor

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_threat_actor(
    name: str = "APT28",
    uid: str = "12345678-1234-5678-1234-567812345678",
) -> ThreatActor:
    return ThreatActor(
        id=f"threat-actor--{uid}",
        created=datetime.now(UTC),
        modified=datetime.now(UTC),
        name=name,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_create() -> AsyncMock:
    """Bare AsyncMock wired as the instructor client's create method."""
    return AsyncMock()


@pytest.fixture
def extractor(mock_create: AsyncMock) -> LLMExtractor:
    """LLMExtractor with instructor and openai fully mocked (no HTTP calls)."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = mock_create
    with (
        patch("src.llm.extractor.openai.AsyncOpenAI"),
        patch("src.llm.extractor.instructor.from_openai", return_value=mock_client),
    ):
        return LLMExtractor()


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_two_threat_actors(
    extractor: LLMExtractor, mock_create: AsyncMock
) -> None:
    """Happy path: mock returns _LLMEntities with 2 threat actors → confidence > 0."""
    actors = [
        _make_threat_actor("APT28", "12345678-1234-5678-1234-567812345671"),
        _make_threat_actor("APT29", "12345678-1234-5678-1234-567812345672"),
    ]
    mock_create.return_value = _LLMEntities(threat_actors=actors)

    result = await extractor.extract(
        event_id="evt-001", text="APT28 and APT29 attacked infrastructure"
    )

    assert result.source_event_id == "evt-001"
    assert len(result.threat_actors) == 2
    assert result.extraction_confidence > 0


@pytest.mark.asyncio
async def test_timeout_fallback_returns_result(
    extractor: LLMExtractor, mock_create: AsyncMock
) -> None:
    """Primary raises asyncio.TimeoutError; fallback succeeds and returns minimal result."""
    actor = _make_threat_actor("APT28", "12345678-1234-5678-1234-567812345671")
    mock_create.side_effect = [
        TimeoutError(),
        _LLMEntities(threat_actors=[actor]),
    ]

    result = await extractor.extract(event_id="evt-002", text="APT28 attacked healthcare")

    assert result.source_event_id == "evt-002"
    assert len(result.threat_actors) == 1


@pytest.mark.asyncio
async def test_all_models_fail_returns_empty_result(
    extractor: LLMExtractor, mock_create: AsyncMock
) -> None:
    """Both primary and fallback time out → empty ExtractionResult, no exception raised."""
    mock_create.side_effect = [TimeoutError(), TimeoutError()]

    result = await extractor.extract(event_id="evt-003", text="some text")

    assert result.source_event_id == "evt-003"
    assert result.extraction_confidence == 0.0
    assert result.threat_actors == []
    assert result.malware == []


@pytest.mark.asyncio
async def test_extract_batch_converts_exceptions_to_empty_results(
    extractor: LLMExtractor,
) -> None:
    """extract_batch: one success + one exception → list with empty result for the exception."""
    actor = _make_threat_actor("APT28", "12345678-1234-5678-1234-567812345671")
    good = ExtractionResult(
        source_event_id="evt-001",
        threat_actors=[actor],
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
    assert len(results[0].threat_actors) == 1
    assert results[1].source_event_id == "evt-002"
    assert results[1].extraction_confidence == 0.0


@pytest.mark.asyncio
async def test_plugin_metadata_propagated(
    extractor: LLMExtractor, mock_create: AsyncMock
) -> None:
    """plugin_id and plugin_version from metadata are set on the result."""
    mock_create.return_value = _LLMEntities()

    result = await extractor.extract(
        event_id="evt-004",
        text="some intelligence text",
        metadata={"plugin_id": "twitter-v1", "plugin_version": "1.2.3"},
    )

    assert result.plugin_id == "twitter-v1"
    assert result.plugin_version == "1.2.3"

