from __future__ import annotations

import logging

from .storage import MinIOStorageService

logger = logging.getLogger(__name__)

_S3_PREFIX = "omni-g-briefings"


class BriefingURLSigner:
    """Return signed MinIO URLs for briefing audio files."""

    def __init__(self, storage: MinIOStorageService, expiry_seconds: int = 3600) -> None:
        self._storage = storage
        self._expiry_seconds = expiry_seconds

    async def sign(self, object_key: str) -> str:
        """Delegate to :meth:`MinIOStorageService.get_signed_url`."""
        return await self._storage.get_signed_url(object_key, self._expiry_seconds)

    async def sign_latest(self, tenant_id: str) -> str | None:
        """Return a signed URL for the most recent briefing audio for *tenant_id*.

        Lists all objects under ``omni-g-briefings/{tenant_id}/`` and returns
        the signed URL for the lexicographically last key (most recent date/UUID).
        Returns ``None`` if no briefings are found.
        """
        prefix = f"{_S3_PREFIX}/{tenant_id}/"
        keys = await self._storage.list_objects(prefix)
        if not keys:
            return None
        latest_key = keys[-1]
        return await self._storage.get_signed_url(latest_key, self._expiry_seconds)
