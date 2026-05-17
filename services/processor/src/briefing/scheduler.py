from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .script_generator import BriefingScriptGenerator
from .storage import MinIOStorageService
from .tts_synthesizer import TTSSynthesizer

logger = logging.getLogger(__name__)


class BriefingScheduler:
    """Schedule daily audio briefings per tenant.

    On :meth:`start`, an :class:`AsyncIOScheduler` job is registered for each
    tenant that runs at ``briefing_hour:00 UTC`` every day.  Call
    :meth:`on_demand` to trigger a briefing immediately for any tenant.
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
        self._scheduler: AsyncIOScheduler | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, tenant_ids: list[str]) -> None:
        """Start the scheduler with daily jobs for each *tenant_id*."""
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        for tenant_id in tenant_ids:
            self._scheduler.add_job(
                self._run_briefing,
                trigger="cron",
                hour=self._briefing_hour,
                minute=0,
                args=[tenant_id],
                id=f"briefing_{tenant_id}",
                replace_existing=True,
            )
            logger.info(
                "briefing_job_scheduled",
                extra={"tenant_id": tenant_id, "hour_utc": self._briefing_hour},
            )
        self._scheduler.start()

    async def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler is not None and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("briefing_scheduler_stopped")

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
