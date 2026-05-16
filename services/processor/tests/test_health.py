from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "processor"


def test_ready_returns_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"


def test_unknown_path_returns_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
