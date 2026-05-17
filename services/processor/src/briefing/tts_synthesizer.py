from __future__ import annotations

import logging

import httpx
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

TTS_REQUESTS = Counter(
    "processor_tts_requests_total",
    "Total TTS synthesis requests",
    ["backend", "status"],
)

TTS_LATENCY = Histogram(
    "processor_tts_latency_seconds",
    "Latency of TTS synthesis calls",
    ["backend"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TTSSynthesisError(Exception):
    """Raised when all TTS backends have failed."""


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

_KOKORO_DEFAULT_VOICE = "af_heart"
_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


class TTSSynthesizer:
    """Synthesize speech from text using Kokoro TTS (primary) or ElevenLabs (fallback)."""

    def __init__(self, kokoro_url: str, elevenlabs_api_key: str | None = None) -> None:
        self._kokoro_url = kokoro_url.rstrip("/")
        self._elevenlabs_api_key = elevenlabs_api_key

    async def synthesize(self, text: str, voice: str = _KOKORO_DEFAULT_VOICE) -> bytes:
        """Synthesize *text* to MP3 audio bytes.

        1. POST to Kokoro TTS endpoint.
        2. On failure, fall back to ElevenLabs if API key is configured.
        3. If both fail, raise :exc:`TTSSynthesisError`.
        """
        import time

        # ── Primary: Kokoro ────────────────────────────────────────────────
        t0 = time.perf_counter()
        try:
            audio = await self._call_kokoro(text, voice)
            TTS_REQUESTS.labels(backend="kokoro", status="success").inc()
            TTS_LATENCY.labels(backend="kokoro").observe(time.perf_counter() - t0)
            logger.info("tts_kokoro_success", extra={"bytes": len(audio)})
            return audio
        except Exception as kokoro_exc:  # noqa: BLE001
            TTS_REQUESTS.labels(backend="kokoro", status="error").inc()
            logger.warning(
                "tts_kokoro_failed",
                extra={"error": str(kokoro_exc)},
            )

        # ── Fallback: ElevenLabs ───────────────────────────────────────────
        if self._elevenlabs_api_key:
            t1 = time.perf_counter()
            try:
                audio = await self._call_elevenlabs(text)
                TTS_REQUESTS.labels(backend="elevenlabs", status="success").inc()
                TTS_LATENCY.labels(backend="elevenlabs").observe(time.perf_counter() - t1)
                logger.info("tts_elevenlabs_success", extra={"bytes": len(audio)})
                return audio
            except Exception as el_exc:  # noqa: BLE001
                TTS_REQUESTS.labels(backend="elevenlabs", status="error").inc()
                logger.error("tts_elevenlabs_failed", extra={"error": str(el_exc)})

        raise TTSSynthesisError(
            "All TTS backends failed. Kokoro and ElevenLabs (if configured) both errored."
        )

    async def _call_kokoro(self, text: str, voice: str) -> bytes:
        """Call the Kokoro TTS /v1/audio/speech endpoint."""
        url = f"{self._kokoro_url}/v1/audio/speech"
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.content

    async def _call_elevenlabs(self, text: str) -> bytes:
        """Call the ElevenLabs text-to-speech API."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVENLABS_VOICE_ID}"
        headers = {"xi-api-key": self._elevenlabs_api_key or ""}
        payload = {"text": text, "model_id": "eleven_monolingual_v1"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.content
