from fastapi.testclient import TestClient


def test_health_response(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "edurage",
        "version": "0.0.1",
    }


def test_unknown_path_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/unknown")

    assert response.status_code == 404
