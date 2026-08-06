"""Tests for BriefingScriptGenerator (V3 — no GraphRAG dependency)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def generator() -> Any:
    from src.briefing.script_generator import BriefingScriptGenerator

    return BriefingScriptGenerator(ollama_url="http://localhost:11434", model="qwen2.5:3b")


@pytest.mark.asyncio()
async def test_generate_with_no_context_returns_placeholder(generator: Any) -> None:
    script = await generator.generate("test-tenant", context=None)
    assert "briefing" in script.lower() or "tenant" in script.lower()


@pytest.mark.asyncio()
async def test_generate_with_context_calls_ollama(generator: Any) -> None:
    context = [{"text": "APT28 targeted healthcare sector."}]
    with patch.object(
        generator, "_call_ollama", new=AsyncMock(return_value="Good morning. Test briefing.")
    ) as mock_call:
        script = await generator.generate("test-tenant", context=context)
        mock_call.assert_called_once_with(context)
        assert script == "Good morning. Test briefing."


@pytest.mark.asyncio()
async def test_generate_falls_back_to_placeholder_on_ollama_error(generator: Any) -> None:
    context = [{"text": "APT28 targeted healthcare sector."}]
    with patch.object(
        generator, "_call_ollama", new=AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    ):
        script = await generator.generate("test-tenant", context=context)
        assert "briefing" in script.lower()


@pytest.mark.asyncio()
async def test_generate_empty_context_uses_placeholder(generator: Any) -> None:
    script = await generator.generate("test-tenant", context=[])
    assert "test-tenant" in script or "briefing" in script.lower()


def test_fallback_script_with_summaries(generator: Any) -> None:
    from src.briefing.script_generator import BriefingScriptGenerator

    summaries = [
        {"text": "Community 1 summary."},
        {"text": "Community 2 summary."},
    ]
    script = BriefingScriptGenerator._fallback_script(summaries)
    assert "Good morning" in script
    assert "Community 1 summary." in script


def test_fallback_script_empty(generator: Any) -> None:
    from src.briefing.script_generator import BriefingScriptGenerator

    script = BriefingScriptGenerator._fallback_script([])
    assert "No intelligence data" in script
