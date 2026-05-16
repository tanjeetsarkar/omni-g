"""Tests for the /validate endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.processor.main import create_app


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


class TestValidateEndpoint:
    def test_valid_payload_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            json={"source": "shodan", "payload": {"ip": "1.2.3.4"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body.get("errors", []) == []

    def test_missing_source_field_returns_422(self, client: TestClient) -> None:
        # Pydantic will reject a missing required field at the model level.
        resp = client.post("/validate", json={"payload": {"ip": "1.2.3.4"}})
        assert resp.status_code == 422

    def test_blank_source_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            json={"source": "   ", "payload": {"ip": "1.2.3.4"}},
        )
        assert resp.status_code == 422

    def test_missing_payload_field_returns_422(self, client: TestClient) -> None:
        resp = client.post("/validate", json={"source": "shodan"})
        assert resp.status_code == 422

    def test_empty_payload_is_valid(self, client: TestClient) -> None:
        """An empty payload dict is allowed; content validation is M3.3 scope."""
        resp = client.post(
            "/validate",
            json={"source": "twitter", "payload": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_non_json_body_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
