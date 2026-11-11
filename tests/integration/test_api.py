from pathlib import Path

from fastapi.testclient import TestClient

from brokej_search.api import create_app


def test_health_profile_and_jobs_api(runtime, resume_path: Path) -> None:
    client = TestClient(create_app(runtime))
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    response = client.post(
        "/candidates/candidate/ingestions", json={"resume_path": str(resume_path)}
    )
    assert response.status_code == 200
    profile = client.get("/candidates/candidate/profile")
    assert profile.status_code == 200
    assert "contact" not in profile.json()
    assert client.get("/jobs").json() == []


def test_api_returns_consistent_not_found(runtime) -> None:
    client = TestClient(create_app(runtime))
    response = client.get("/jobs/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
