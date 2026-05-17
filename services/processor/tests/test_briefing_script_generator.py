from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_graphrag_indexer() -> AsyncMock:
    indexer = AsyncMock()
    indexer.get_community_summaries.return_value = [
        {
            "community_id": 1,
            "community_summary": "APT28 targeted healthcare sector.",
            "entity_count": 3,
        },
        {
            "community_id": 2,
            "community_summary": "Emotet malware distributed via phishing.",
            "entity_count": 2,
        },
    ]
    return indexer


@pytest.fixture()
def mock_llm_extractor_for_briefing() -> MagicMock:
    """Mock LLM extractor with an async client for briefing tests."""
    extractor = MagicMock()
    mock_client = AsyncMock()
    mock_response = MagicMock()
    _good_morning = (
        "Good morning. Here is your intelligence briefing. "
        "Today's key threats include APT28 targeting healthcare."
    )
    mock_response.choices = [MagicMock(message=MagicMock(content=_good_morning))]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    extractor._client = mock_client
    return extractor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBriefingScriptGenerator:
    async def test_script_starts_with_good_morning_when_llm_succeeds(
        self,
        mock_graphrag_indexer: AsyncMock,
        mock_llm_extractor_for_briefing: MagicMock,
    ) -> None:
        """Generated script starts with 'Good morning' when LLM succeeds."""
        from src.briefing.script_generator import BriefingScriptGenerator

        gen = BriefingScriptGenerator(mock_graphrag_indexer, mock_llm_extractor_for_briefing)
        script = await gen.generate("default")
        assert script.startswith("Good morning")

    async def test_fallback_to_concatenated_summaries_when_llm_raises(
        self,
        mock_graphrag_indexer: AsyncMock,
        mock_llm_extractor_for_briefing: MagicMock,
    ) -> None:
        """Falls back to concatenating summaries when LLM raises an exception."""
        from src.briefing.script_generator import BriefingScriptGenerator

        mock_llm_extractor_for_briefing._client.chat.completions.create.side_effect = RuntimeError(
            "LLM unavailable"
        )
        gen = BriefingScriptGenerator(mock_graphrag_indexer, mock_llm_extractor_for_briefing)
        script = await gen.generate("default")
        # Fallback always starts with "Good morning"
        assert script.startswith("Good morning")
        # And should contain community summaries
        assert "APT28" in script or "Emotet" in script or "Community" in script

    async def test_fallback_when_no_summaries(
        self,
        mock_llm_extractor_for_briefing: MagicMock,
    ) -> None:
        """Fallback script handles empty summaries gracefully."""
        from src.briefing.script_generator import BriefingScriptGenerator

        empty_indexer = AsyncMock()
        empty_indexer.get_community_summaries.return_value = []
        mock_llm_extractor_for_briefing._client.chat.completions.create.side_effect = RuntimeError(
            "LLM unavailable"
        )
        gen = BriefingScriptGenerator(empty_indexer, mock_llm_extractor_for_briefing)
        script = await gen.generate("default")
        assert "Good morning" in script
        assert "No intelligence" in script

    async def test_get_community_summaries_called_with_tenant_id(
        self,
        mock_graphrag_indexer: AsyncMock,
        mock_llm_extractor_for_briefing: MagicMock,
    ) -> None:
        """Correct tenant_id is passed to get_community_summaries."""
        from src.briefing.script_generator import BriefingScriptGenerator

        gen = BriefingScriptGenerator(mock_graphrag_indexer, mock_llm_extractor_for_briefing)
        await gen.generate("acme-corp")
        mock_graphrag_indexer.get_community_summaries.assert_called_once_with("acme-corp")

    async def test_prometheus_error_counter_increments_on_llm_failure(
        self,
        mock_graphrag_indexer: AsyncMock,
        mock_llm_extractor_for_briefing: MagicMock,
    ) -> None:
        """BRIEFING_SCRIPT_ERRORS counter increments when LLM fails."""
        from src.briefing.script_generator import BRIEFING_SCRIPT_ERRORS, BriefingScriptGenerator

        def _counter_value(counter: Any) -> float:
            value_obj = getattr(counter, "_value", None)
            if value_obj is None:
                return 0.0
            return float(value_obj.get())

        mock_llm_extractor_for_briefing._client.chat.completions.create.side_effect = RuntimeError(
            "LLM error"
        )
        gen = BriefingScriptGenerator(mock_graphrag_indexer, mock_llm_extractor_for_briefing)
        before = _counter_value(BRIEFING_SCRIPT_ERRORS)
        await gen.generate("default")
        assert _counter_value(BRIEFING_SCRIPT_ERRORS) == before + 1
