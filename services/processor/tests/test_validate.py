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
            json={"source": "http://shodan.io", "payload": {"text": "suspicious host 1.2.3.4"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body.get("errors", []) == []

    def test_missing_source_field_returns_422(self, client: TestClient) -> None:
        # Pydantic will reject a missing required field at the model level.
        resp = client.post("/validate", json={"payload": {"text": "data"}})
        assert resp.status_code == 422

    def test_blank_source_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            json={"source": "   ", "payload": {"text": "data"}},
        )
        assert resp.status_code == 422

    def test_non_url_source_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            json={"source": "shodan", "payload": {"text": "data"}},
        )
        assert resp.status_code == 422

    def test_missing_payload_field_returns_422(self, client: TestClient) -> None:
        resp = client.post("/validate", json={"source": "http://shodan.io"})
        assert resp.status_code == 422

    def test_empty_payload_returns_invalid(self, client: TestClient) -> None:
        """An empty payload dict is rejected by stricter content validation."""
        resp = client.post(
            "/validate",
            json={"source": "http://twitter.com", "payload": {}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        assert len(body["errors"]) > 0

    def test_payload_without_content_key_returns_invalid(self, client: TestClient) -> None:
        """Payload missing text/content/data/url is rejected."""
        resp = client.post(
            "/validate",
            json={"source": "http://shodan.io", "payload": {"ip": "1.2.3.4"}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        assert any(e["field"] == "payload" for e in body["errors"])

    def test_payload_with_none_value_returns_invalid(self, client: TestClient) -> None:
        """Payload with a None top-level value is rejected."""
        resp = client.post(
            "/validate",
            json={"source": "http://shodan.io", "payload": {"text": None}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False

    def test_payload_with_empty_string_value_returns_invalid(self, client: TestClient) -> None:
        """Payload with an empty-string top-level value is rejected."""
        resp = client.post(
            "/validate",
            json={"source": "http://shodan.io", "payload": {"text": ""}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False

    def test_errors_are_structured_objects(self, client: TestClient) -> None:
        """Each error entry has 'field' and 'message' keys."""
        resp = client.post(
            "/validate",
            json={"source": "http://shodan.io", "payload": {}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["valid"] is False
        for err in body["errors"]:
            assert "field" in err
            assert "message" in err

    def test_non_json_body_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/validate",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
