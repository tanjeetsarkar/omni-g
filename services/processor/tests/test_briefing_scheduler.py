from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def mock_script_generator() -> AsyncMock:
    gen = AsyncMock()
    gen.generate.return_value = "Good morning. Here is your intelligence briefing. Today: APT28."
    return gen


@pytest.fixture()
def mock_tts_synthesizer() -> AsyncMock:
    tts = AsyncMock()
    tts.synthesize.return_value = b"fake-mp3-audio"
    return tts


@pytest.fixture()
def mock_storage() -> AsyncMock:
    storage = AsyncMock()
    storage.upload_audio.return_value = "omni-g-briefings/tenant1/2024-01-15/abc.mp3"
    storage.get_signed_url.return_value = "https://minio/signed-url"
    return storage


class TestBriefingScheduler:
    async def test_on_demand_calls_all_three_in_sequence(
        self,
        mock_script_generator: AsyncMock,
        mock_tts_synthesizer: AsyncMock,
        mock_storage: AsyncMock,
    ) -> None:
        """on_demand() calls script gen → TTS → storage in sequence."""
        from src.briefing.scheduler import BriefingScheduler

        scheduler = BriefingScheduler(
            script_generator=mock_script_generator,
            tts_synthesizer=mock_tts_synthesizer,
            storage=mock_storage,
        )
        key = await scheduler.on_demand("tenant1")

        mock_script_generator.generate.assert_called_once_with("tenant1")
        mock_tts_synthesizer.synthesize.assert_called_once_with(
            "Good morning. Here is your intelligence briefing. Today: APT28."
        )
        mock_storage.upload_audio.assert_called_once_with("tenant1", b"fake-mp3-audio")
        assert key == "omni-g-briefings/tenant1/2024-01-15/abc.mp3"

    async def test_on_demand_returns_object_key(
        self,
        mock_script_generator: AsyncMock,
        mock_tts_synthesizer: AsyncMock,
        mock_storage: AsyncMock,
    ) -> None:
        """on_demand() returns the object key from storage.upload_audio."""
        from src.briefing.scheduler import BriefingScheduler

        scheduler = BriefingScheduler(mock_script_generator, mock_tts_synthesizer, mock_storage)
        key = await scheduler.on_demand("tenant1")
        assert key == "omni-g-briefings/tenant1/2024-01-15/abc.mp3"
