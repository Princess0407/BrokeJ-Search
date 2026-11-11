from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from brokej_search.api import create_app
from brokej_search.database.models import Candidate, GitHubProfile, Job


def test_http_routes_ingest_and_serialize_profile(runtime: Any, resume_path: Path) -> None:
    async def request() -> None:
        transport = httpx.ASGITransport(app=create_app(runtime))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/healthz")).json() == {"status": "ok"}
            assert (await client.get("/readyz")).json() == {"status": "ready"}

            response = await client.post(
                "/candidates/http-candidate/ingestions",
                json={"resume_path": str(resume_path)},
            )
            assert response.status_code == 200
            assert response.json()["candidate_id"] == "http-candidate"
            profile = await client.get("/candidates/http-candidate/profile")
            assert profile.status_code == 200
            assert "contact" not in profile.json()
            assert (await client.get("/jobs")).json() == []

    asyncio.run(request())


def test_http_validation_methods_and_database_scope(runtime: Any, resume_path: Path) -> None:
    with runtime.factory.begin() as session:
        session.add(Candidate(id="http-github-candidate"))
        session.add(
            Job(
                id="http-job",
                title="Backend Engineer",
                normalized_title="backend engineer",
                company_name="Example",
                normalized_company="example",
                description_text="Must build Python services.",
                listing_url="https://jobs.example/http-job",
                required_skills=["Python"],
                preferred_skills=[],
                status="active",
            )
        )

    async def request() -> None:
        transport = httpx.ASGITransport(app=create_app(runtime))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing_body = await client.put("/candidates/http-github-candidate/github", json={})
            assert missing_body.status_code == 422
            wrong_method = await client.put("/healthz")
            assert wrong_method.status_code == 405

            ingested = await client.post(
                "/candidates/http-github-candidate/ingestions",
                json={"resume_path": str(resume_path)},
            )
            assert ingested.status_code == 200

            requirements = await client.get("/jobs/http-job/requirements")
            assert requirements.status_code == 200
            assert any(item["normalized_competency"] == "Python" for item in requirements.json())
            assessment = await client.post(
                "/candidates/http-github-candidate/jobs/http-job/assessment"
            )
            assert assessment.status_code == 200
            assert assessment.json()["job_id"] == "http-job"
            configured = await client.put(
                "/candidates/http-github-candidate/github",
                json={
                    "username_or_url": "https://github.com/alice",
                    "authorized": True,
                    "ownership_confirmed": True,
                },
            )
            assert configured.status_code == 200
            assert configured.json()["ownership_status"] == "candidate_confirmed"
            findings = await client.post("/candidates/http-github-candidate/github/reconciliations")
            assert findings.status_code == 200
            if findings.json():
                corrected = await client.patch(
                    "/candidates/http-github-candidate/github/reconciliations/"
                    f"{findings.json()[0]['id']}",
                    json={"classification": "partially_supported", "note": "Candidate note"},
                )
                assert corrected.status_code == 200
                assert corrected.json()["candidate_note"] == "Candidate note"
            disabled = await client.delete("/candidates/http-github-candidate/github")
            assert disabled.status_code == 204

    asyncio.run(request())
    with runtime.factory() as session:
        profile = session.scalar(
            select(GitHubProfile).where(GitHubProfile.candidate_id == "http-github-candidate")
        )
        assert profile is not None and not profile.enabled and not profile.analysis_authorized


def test_http_error_responses_and_unexpected_failure(
    runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def request() -> None:
        transport = httpx.ASGITransport(app=create_app(runtime))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            missing = await client.get("/jobs/missing")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "not_found"

        monkeypatch.setattr(
            runtime.discovery,
            "list_jobs",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("test failure")),
        )
        failing_transport = httpx.ASGITransport(app=create_app(runtime), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=failing_transport, base_url="http://test") as client:
            response = await client.get("/jobs")
            assert response.status_code == 500

    asyncio.run(request())
