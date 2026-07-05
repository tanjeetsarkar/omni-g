from __future__ import annotations

import logging

from .script_generator import BriefingScriptGenerator
from .storage import MinIOStorageService
from .tts_synthesizer import TTSSynthesizer

logger = logging.getLogger(__name__)


class BriefingScheduler:
    """On-demand audio briefing runner per tenant.

    Call :meth:`on_demand` to trigger a briefing immediately for any tenant.
    Recurring scheduled execution is handled by Celery Beat
    (``CELERY_BRIEFING_ENABLED=true``).
    """

    def __init__(
        self,
        script_generator: BriefingScriptGenerator,
        tts_synthesizer: TTSSynthesizer,
        storage: MinIOStorageService,
        briefing_hour: int = 8,
    ) -> None:
        self._script_generator = script_generator
        self._tts = tts_synthesizer
        self._storage = storage
        self._briefing_hour = briefing_hour

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
