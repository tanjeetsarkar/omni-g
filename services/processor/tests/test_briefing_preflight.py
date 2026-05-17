from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.processor.config import Settings
from src.processor.main import create_app


def _settings(**overrides: object) -> Settings:
    base = {
        "LOG_LEVEL": "debug",
        "HTTP_PORT": 8001,
        "KAFKA_ENABLED": False,
        "BRIEFING_PREFLIGHT_ENABLED": True,
        "BRIEFING_PREFLIGHT_STRICT": False,
    }
    base.update(overrides)
    return Settings(**base)


class TestBriefingPreflight:
    def test_preflight_runs_when_enabled(self) -> None:
        settings = _settings()

        with patch(
            "src.processor.main.startup_briefing_storage_preflight", new=AsyncMock()
        ) as mock_preflight:
            app = create_app(settings)
            with TestClient(app) as client:
                response = client.get("/health")
                assert response.status_code == 200

        mock_preflight.assert_awaited_once()

    def test_preflight_failure_continues_when_non_strict(self) -> None:
        settings = _settings(BRIEFING_PREFLIGHT_STRICT=False)

        with patch(
            "src.processor.main.startup_briefing_storage_preflight",
            new=AsyncMock(side_effect=RuntimeError("minio unavailable")),
        ):
            app = create_app(settings)
            with TestClient(app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_preflight_failure_raises_when_strict(self) -> None:
        settings = _settings(BRIEFING_PREFLIGHT_STRICT=True)

        with patch(
            "src.processor.main.startup_briefing_storage_preflight",
            new=AsyncMock(side_effect=RuntimeError("minio unavailable")),
        ):
            app = create_app(settings)
            with pytest.raises(RuntimeError, match="minio unavailable"):
                with TestClient(app):
                    pass

    def test_preflight_not_run_when_disabled(self) -> None:
        settings = _settings(BRIEFING_PREFLIGHT_ENABLED=False)

        with patch(
            "src.processor.main.startup_briefing_storage_preflight", new=AsyncMock()
        ) as mock_preflight:
            app = create_app(settings)
            with TestClient(app) as client:
                response = client.get("/ready")
                assert response.status_code == 200

        mock_preflight.assert_not_awaited()
