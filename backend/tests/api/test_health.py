from fastapi.testclient import TestClient


def test_health_live_returns_200_and_ok_status(client: TestClient) -> None:
    url = client.app.url_path_for("health_live")
    response = client.get(url)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] != ""
