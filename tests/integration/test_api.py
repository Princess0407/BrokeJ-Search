import asyncio
import json
from pathlib import Path
from typing import Any

from brokej_search.api import GitHubProfileRequest, IngestRequest, create_app
from brokej_search.core.exceptions import BrokeJError, NotFoundError
from brokej_search.database.models import Candidate, GitHubProfile, Job


def _endpoint(app: Any, path: str, method: str = "GET") -> Any:
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )


def test_health_profile_and_jobs_api(runtime, resume_path: Path) -> None:
    app = create_app(runtime)
    assert _endpoint(app, "/healthz")() == {"status": "ok"}
    assert _endpoint(app, "/readyz")() == {"status": "ready"}
    result = _endpoint(app, "/candidates/{candidate_id}/ingestions", "POST")(
        "candidate", IngestRequest(resume_path=str(resume_path))
    )
    assert result["candidate_id"] == "candidate"
    profile = _endpoint(app, "/candidates/{candidate_id}/profile")("candidate")
    assert "contact" not in profile
    assert _endpoint(app, "/jobs")(None, 100) == []


def test_api_returns_consistent_not_found(runtime) -> None:
    app = create_app(runtime)
    try:
        _endpoint(app, "/jobs/{job_id}")("missing")
    except NotFoundError as exc:
        handler = app.exception_handlers[BrokeJError]
        response = asyncio.run(handler(None, exc))
    else:
        raise AssertionError("Missing job did not raise NotFoundError")
    assert response.status_code == 404
    assert json.loads(response.body)["error"]["code"] == "not_found"


def test_api_exposes_requirements_assessment_and_github_consent(runtime) -> None:
    with runtime.factory.begin() as session:
        session.add(Candidate(id="api-candidate"))
        session.add(
            Job(
                id="api-job",
                title="Backend Engineer",
                normalized_title="backend engineer",
                company_name="Example",
                normalized_company="example",
                description_text="Must build Python services.",
                listing_url="https://jobs.example/api-job",
                required_skills=["Python"],
                preferred_skills=[],
                status="active",
            )
        )
    app = create_app(runtime)
    requirements = _endpoint(app, "/jobs/{job_id}/requirements")("api-job")
    assert any(item["normalized_competency"] == "Python" for item in requirements)
    profile = _endpoint(app, "/candidates/{candidate_id}/github", "PUT")(
        "api-candidate",
        GitHubProfileRequest(username_or_url="alice", authorized=True, ownership_confirmed=True),
    )
    assert profile["authorized"] is True
    assert profile["ownership_status"] == "candidate_confirmed"
    _endpoint(app, "/candidates/{candidate_id}/github", "DELETE")("api-candidate")
    with runtime.factory() as session:
        saved_profile = session.query(GitHubProfile).one()
        assert saved_profile.enabled is False
        assert saved_profile.analysis_authorized is False
