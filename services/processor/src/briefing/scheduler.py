from __future__ import annotations

import logging

from .script_generator import BriefingScriptGenerator
from .storage import MinIOStorageService
from .tts_synthesizer import TTSSynthesizer

logger = logging.getLogger(__name__)


class BriefingScheduler:
    """Stateless runner for audio briefing generation.

    Scheduled execution is handled externally by Celery Beat.  Call
    :meth:`on_demand` directly from a Celery task to generate a briefing for a
    tenant immediately.
    """

    def __init__(
        self,
        script_generator: BriefingScriptGenerator,
        tts_synthesizer: TTSSynthesizer,
        storage: MinIOStorageService,
    ) -> None:
        self._script_generator = script_generator
        self._tts = tts_synthesizer
        self._storage = storage

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def on_demand(self, tenant_id: str) -> str:
        """Generate, synthesize, upload, and return the object key immediately."""
        script = await self._script_generator.generate(tenant_id)
        audio_bytes = await self._tts.synthesize(script)
        object_key = await self._storage.upload_audio(tenant_id, audio_bytes)
        logger.info(
            "briefing_on_demand_complete",
            extra={"tenant_id": tenant_id, "object_key": object_key},
        )
        return object_key

    # ------------------------------------------------------------------
    # Internal job handler
    # ------------------------------------------------------------------

    async def _run_briefing(self, tenant_id: str) -> None:
        """Generate, synthesize, upload briefing for *tenant_id* and log result."""
        try:
            object_key = await self.on_demand(tenant_id)
            logger.info(
                "scheduled_briefing_complete",
                extra={"tenant_id": tenant_id, "object_key": object_key},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "scheduled_briefing_failed",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )
