from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import aioboto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_S3_PREFIX = "omni-g-briefings"


class MinIOStorageService:
    """Upload audio files to MinIO (S3-compatible object storage)."""

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_audio(
        self,
        tenant_id: str,
        audio_bytes: bytes,
        date_str: str | None = None,
    ) -> str:
        """Upload *audio_bytes* to MinIO and return the object key.

        Key format: ``omni-g-briefings/{tenant_id}/{date_str or today}/{uuid4}.mp3``
        """
        date_part = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
        object_key = f"{_S3_PREFIX}/{tenant_id}/{date_part}/{uuid4()}.mp3"

        s3_client = cast(
            Any,
            self._session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name="us-east-1",
            ),
        )
        async with s3_client as s3:
            await self._ensure_bucket(s3)
            await s3.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=audio_bytes,
                ContentType="audio/mpeg",
            )

        logger.info(
            "briefing_audio_uploaded",
            extra={"bucket": self._bucket, "key": object_key, "bytes": len(audio_bytes)},
        )
        return object_key

    async def get_signed_url(self, object_key: str, expiry_seconds: int = 3600) -> str:
        """Generate a presigned GET URL for *object_key*."""
        s3_client = cast(
            Any,
            self._session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name="us-east-1",
            ),
        )
        async with s3_client as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=expiry_seconds,
            )
        return url

    async def ensure_bucket(self) -> None:
        """Ensure the configured bucket exists before briefing operations run."""
        s3_client = cast(
            Any,
            self._session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name="us-east-1",
            ),
        )
        async with s3_client as s3:
            await self._ensure_bucket(s3)

    async def list_objects(self, prefix: str) -> list[str]:
        """List object keys under *prefix*.  Returns keys sorted ascending."""
        s3_client = cast(
            Any,
            self._session.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name="us-east-1",
            ),
        )
        async with s3_client as s3:
            await self._ensure_bucket(s3)
            response = await s3.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        contents = response.get("Contents", [])
        return sorted(obj["Key"] for obj in contents)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ensure_bucket(self, s3: object) -> None:
        """Create the bucket if it does not already exist."""
        try:
            await s3.head_bucket(Bucket=self._bucket)  # type: ignore[attr-defined]
        except ClientError:
            try:
                await s3.create_bucket(Bucket=self._bucket)  # type: ignore[attr-defined]
                logger.info("briefing_bucket_created", extra={"bucket": self._bucket})
            except ClientError as exc:
                logger.warning(
                    "briefing_bucket_create_failed",
                    extra={"bucket": self._bucket, "error": str(exc)},
                )
