from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


def _make_storage() -> object:
    """Create MinIOStorageService with mocked session."""
    from src.briefing.storage import MinIOStorageService

    storage = MinIOStorageService(
        endpoint_url="http://minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin",  # noqa: S106
        bucket="omni-g-briefings",
    )
    return storage


class TestMinIOStorageService:
    async def test_upload_audio_calls_put_object_with_correct_key_format(self) -> None:
        """upload_audio calls put_object with the correct key format."""
        from src.briefing.storage import MinIOStorageService

        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(return_value={})
        mock_s3.put_object = AsyncMock(return_value={})
        mock_s3.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_s3.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        with patch("aioboto3.Session", return_value=mock_session):
            storage = MinIOStorageService(
                endpoint_url="http://minio:9000",
                access_key="minioadmin",
                secret_key="minioadmin",  # noqa: S106
                bucket="omni-g-briefings",
            )
            object_key = await storage.upload_audio(
                tenant_id="acme",
                audio_bytes=b"fake-audio",
                date_str="2024-01-15",
            )

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "omni-g-briefings"
        assert call_kwargs["ContentType"] == "audio/mpeg"
        assert object_key.startswith("omni-g-briefings/acme/2024-01-15/")
        assert object_key.endswith(".mp3")

    async def test_upload_audio_uses_today_when_no_date_str(self) -> None:
        """upload_audio uses today's date when date_str is not provided."""
        from datetime import UTC, datetime

        from src.briefing.storage import MinIOStorageService

        today = datetime.now(UTC).strftime("%Y-%m-%d")

        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(return_value={})
        mock_s3.put_object = AsyncMock(return_value={})
        mock_s3.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_s3.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        with patch("aioboto3.Session", return_value=mock_session):
            storage = MinIOStorageService(
                endpoint_url="http://minio:9000",
                access_key="minioadmin",
                secret_key="minioadmin",  # noqa: S106
                bucket="omni-g-briefings",
            )
            object_key = await storage.upload_audio(
                tenant_id="tenant1",
                audio_bytes=b"audio",
            )

        assert f"/tenant1/{today}/" in object_key

    async def test_get_signed_url_calls_generate_presigned_url(self) -> None:
        """get_signed_url delegates to s3.generate_presigned_url."""
        from src.briefing.storage import MinIOStorageService

        fake_url = "https://minio:9000/omni-g-briefings/key.mp3?signature=abc"

        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(return_value=fake_url)
        mock_s3.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_s3.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        with patch("aioboto3.Session", return_value=mock_session):
            storage = MinIOStorageService(
                endpoint_url="http://minio:9000",
                access_key="minioadmin",
                secret_key="minioadmin",  # noqa: S106
                bucket="omni-g-briefings",
            )
            url = await storage.get_signed_url("omni-g-briefings/tenant1/2024-01-15/abc.mp3")

        assert url == fake_url
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "omni-g-briefings",
                "Key": "omni-g-briefings/tenant1/2024-01-15/abc.mp3",
            },
            ExpiresIn=3600,
        )

    async def test_bucket_created_when_not_exists(self) -> None:
        """_ensure_bucket creates bucket when head_bucket raises ClientError."""
        from botocore.exceptions import ClientError

        from src.briefing.storage import MinIOStorageService

        mock_s3 = AsyncMock()
        _client_err = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")
        mock_s3.head_bucket = AsyncMock(side_effect=_client_err)
        mock_s3.create_bucket = AsyncMock(return_value={})
        mock_s3.put_object = AsyncMock(return_value={})
        mock_s3.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_s3.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        with patch("aioboto3.Session", return_value=mock_session):
            storage = MinIOStorageService(
                endpoint_url="http://minio:9000",
                access_key="minioadmin",
                secret_key="minioadmin",  # noqa: S106
                bucket="omni-g-briefings",
            )
            await storage.upload_audio("t1", b"audio", "2024-01-15")

        mock_s3.create_bucket.assert_called_once_with(Bucket="omni-g-briefings")

    async def test_list_objects_creates_missing_bucket_and_returns_empty(self) -> None:
        """list_objects should create missing bucket and return [] when there are no keys."""
        from botocore.exceptions import ClientError

        from src.briefing.storage import MinIOStorageService

        mock_s3 = AsyncMock()
        _client_err = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")
        mock_s3.head_bucket = AsyncMock(side_effect=_client_err)
        mock_s3.create_bucket = AsyncMock(return_value={})
        mock_s3.list_objects_v2 = AsyncMock(return_value={})
        mock_s3.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_s3.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.client.return_value = mock_s3

        with patch("aioboto3.Session", return_value=mock_session):
            storage = MinIOStorageService(
                endpoint_url="http://minio:9000",
                access_key="minioadmin",
                secret_key="minioadmin",  # noqa: S106
                bucket="omni-g-briefings",
            )
            keys = await storage.list_objects("omni-g-briefings/default/")

        assert keys == []
        mock_s3.create_bucket.assert_called_once_with(Bucket="omni-g-briefings")
