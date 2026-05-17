from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTTSSynthesizer:
    async def test_returns_bytes_on_kokoro_success(self) -> None:
        """Returns audio bytes when Kokoro responds successfully."""
        from src.briefing.tts_synthesizer import TTSSynthesizer

        fake_audio = b"fake-mp3-data"
        mock_response = MagicMock()
        mock_response.content = fake_audio
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            synth = TTSSynthesizer(kokoro_url="http://kokoro:8880")
            result = await synth.synthesize("Hello world")

        assert result == fake_audio

    async def test_fallback_to_elevenlabs_on_kokoro_failure(self) -> None:
        """Falls back to ElevenLabs when Kokoro raises an error."""
        from src.briefing.tts_synthesizer import TTSSynthesizer

        fake_elevenlabs_audio = b"elevenlabs-mp3-data"
        call_count = 0

        async def fake_post(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if "kokoro" in url or "8880" in url:
                raise Exception("Kokoro unavailable")
            # ElevenLabs call
            mock_resp = MagicMock()
            mock_resp.content = fake_elevenlabs_audio
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = fake_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            synth = TTSSynthesizer(
                kokoro_url="http://kokoro:8880",
                elevenlabs_api_key="test-api-key",
            )
            result = await synth.synthesize("Hello world")

        assert result == fake_elevenlabs_audio

    async def test_raises_tts_synthesis_error_when_both_fail(self) -> None:
        """Raises TTSSynthesisError when both Kokoro and ElevenLabs fail."""
        from src.briefing.tts_synthesizer import TTSSynthesisError, TTSSynthesizer

        async def always_raise(url: str, **kwargs: object) -> None:
            raise Exception("network error")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = always_raise
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            synth = TTSSynthesizer(
                kokoro_url="http://kokoro:8880",
                elevenlabs_api_key="test-key",
            )
            with pytest.raises(TTSSynthesisError):
                await synth.synthesize("Hello world")

    async def test_raises_tts_error_when_no_elevenlabs_key(self) -> None:
        """Raises TTSSynthesisError immediately after Kokoro fails if no ElevenLabs key."""
        from src.briefing.tts_synthesizer import TTSSynthesisError, TTSSynthesizer

        async def kokoro_fail(url: str, **kwargs: object) -> None:
            raise Exception("Kokoro down")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = kokoro_fail
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            synth = TTSSynthesizer(kokoro_url="http://kokoro:8880")  # no ElevenLabs key
            with pytest.raises(TTSSynthesisError):
                await synth.synthesize("Hello world")

    async def test_prometheus_tts_counter_increments_on_success(self) -> None:
        """processor_tts_requests_total increments for kokoro/success."""
        from typing import Any

        from src.briefing.tts_synthesizer import TTS_REQUESTS, TTSSynthesizer

        def _counter_value(counter: Any, **labels: str) -> float:
            metric = counter.labels(**labels) if labels else counter
            value_obj = getattr(metric, "_value", None)
            if value_obj is None:
                return 0.0
            return float(value_obj.get())

        fake_audio = b"audio-bytes"
        mock_response = MagicMock()
        mock_response.content = fake_audio
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            synth = TTSSynthesizer(kokoro_url="http://kokoro:8880")
            before = _counter_value(TTS_REQUESTS, backend="kokoro", status="success")
            await synth.synthesize("test text")
            assert _counter_value(TTS_REQUESTS, backend="kokoro", status="success") == before + 1
