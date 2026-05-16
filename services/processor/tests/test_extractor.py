import pytest

from src.llm.extractor import LLMExtractor


@pytest.mark.asyncio
async def test_extractor_returns_result_with_correct_event_id() -> None:
    extractor = LLMExtractor(ollama_url="http://localhost:11434")
    result = await extractor.extract(event_id="evt-abc", text="APT28 attacked infrastructure")
    assert result.source_event_id == "evt-abc"


@pytest.mark.asyncio
async def test_extractor_stub_returns_zero_confidence() -> None:
    """Stub implementation must return 0.0 confidence until M3.3 is wired."""
    extractor = LLMExtractor(ollama_url="http://localhost:11434")
    result = await extractor.extract(event_id="evt-001", text="some text")
    assert result.extraction_confidence == 0.0
