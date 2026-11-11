from __future__ import annotations

import asyncio
import base64

import httpx
import pytest
from sqlalchemy import func, select

from brokej_search.core.exceptions import ConnectorError, GitHubRateLimitError
from brokej_search.database.models import (
    Candidate,
    ClaimReconciliation,
    EntityStatement,
    GitHubContribution,
    GitHubProfile,
    GitHubRepository,
    ProfileEntity,
    ProfileVersion,
    RepositoryAnalysis,
    SourceDocument,
    SourceFragment,
)
from brokej_search.github.analysis import analyze_repository, reconcile_claim
from brokej_search.github.client import GitHubClient
from brokej_search.github.service import GitHubService, decode_content


def test_profile_lookup_and_repository_pagination() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/users/alice":
            return httpx.Response(200, json={"login": "alice", "id": 1}, headers={"etag": '"u1"'})
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"link": '<https://api.github.com/users/alice/repos?page=2>; rel="next"'},
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GitHubClient(http)
            user, headers = await client.get_json("/users/alice")
            repos = await client.paginated("/users/alice/repos", max_items=10)
            assert user == {"login": "alice", "id": 1}
            assert headers["etag"] == '"u1"'
            assert [repo["id"] for repo in repos] == [1, 2]

    asyncio.run(run())
    assert len(requests) == 3


def test_rate_limit_network_retry_and_missing_repository() -> None:
    calls = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(404)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(retry_handler)) as http:
            client = GitHubClient(http, sleep=_no_sleep)
            payload, _ = await client.get_json("/repos/alice/missing")
            assert payload is None
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    403,
                    headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1"},
                )
            )
        ) as http:
            with pytest.raises(GitHubRateLimitError):
                await GitHubClient(http).get_json("/users/alice")

    asyncio.run(run())
    assert calls == 2


async def _no_sleep(_: float) -> None:
    return None


def test_repository_analysis_distinguishes_source_forks_and_claim_support() -> None:
    repo = {"id": 1, "description": "API", "fork": False, "archived": False}
    analysis = analyze_repository(
        repo,
        ["app/main.py", "tests/test_api.py", "pyproject.toml", ".github/workflows/test.yml"],
        {"app/main.py": "from fastapi import FastAPI\napp = FastAPI()"},
        "# API",
    )
    assert analysis["classification"] == "substantial_implementation"
    assert analysis["signals"]["fastapi_implementation"] is True
    assert reconcile_claim("Developed a FastAPI backend", [analysis])[0] == "supported"
    fork = analyze_repository({**repo, "fork": True}, ["main.py"], {}, None)
    assert fork["classification"] == "fork"
    assert reconcile_claim("Built Kubernetes infrastructure", [analysis])[0] == "unverified"


def test_oversized_content_is_not_retained() -> None:
    small = {"encoding": "base64", "content": base64.b64encode(b"safe").decode()}
    large = {"encoding": "base64", "content": base64.b64encode(b"x" * 10).decode()}
    assert decode_content(small) == "safe"
    assert decode_content(large, max_bytes=5) is None


def test_candidate_opt_out_and_fresh_cache(runtime) -> None:
    with runtime.factory.begin() as session:
        session.add(Candidate(id="candidate-github"))
    service = GitHubService(runtime.factory)
    configured = service.configure("candidate-github", "https://github.com/alice", authorized=False)
    assert configured["enabled"] is False
    assert asyncio.run(service.sync("candidate-github")) == {
        "status": "disabled",
        "repositories": 0,
        "contributions": 0,
    }


def test_client_refuses_untrusted_pagination_host() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ) as http:
            with pytest.raises(ConnectorError):
                await GitHubClient(http).get_json("https://example.com/not-github")

    asyncio.run(run())


def test_optional_sync_persists_bounded_public_evidence_and_uses_fresh_cache(runtime) -> None:
    with runtime.factory.begin() as session:
        session.add(Candidate(id="candidate-sync"))
    requests: list[str] = []
    source = base64.b64encode(b"from fastapi import FastAPI\napp = FastAPI()").decode()
    readme = base64.b64encode(b"# Example").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        path = request.url.path
        if path == "/users/alice":
            return httpx.Response(200, json={"id": 7}, headers={"etag": '"alice-1"'})
        if path == "/users/alice/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 10,
                        "full_name": "alice/api",
                        "html_url": "https://github.com/alice/api",
                        "description": "API",
                        "private": False,
                        "fork": False,
                        "archived": False,
                        "default_branch": "main",
                        "updated_at": "2026-11-01T00:00:00Z",
                    },
                    {"id": 11, "private": True},
                ],
            )
        if path.endswith("/languages"):
            return httpx.Response(200, json={"Python": 100})
        if "/git/trees/" in path:
            return httpx.Response(
                200,
                json={
                    "tree": [
                        {"path": "main.py"},
                        {"path": "tests/test_api.py"},
                        {"path": "pyproject.toml"},
                    ]
                },
            )
        if path.endswith("/contents/main.py"):
            return httpx.Response(200, json={"encoding": "base64", "content": source})
        if path.endswith("/contents/pyproject.toml"):
            return httpx.Response(200, json={"encoding": "base64", "content": ""})
        if path.endswith("/readme"):
            return httpx.Response(200, json={"encoding": "base64", "content": readme})
        if path == "/search/issues":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "url": f"https://api.github.com/repos/org/repo/issues/{len(requests)}",
                            "repository_url": "https://api.github.com/repos/org/repo",
                            "html_url": "https://github.com/org/repo/pull/1",
                            "state": "closed",
                            "number": 1,
                            "created_at": "2026-10-01T00:00:00Z",
                            "pull_request": {"merged_at": "2026-10-02T00:00:00Z"},
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async def run() -> tuple[dict, dict]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            service = GitHubService(runtime.factory, GitHubClient(http))
            service.configure("candidate-sync", "alice", authorized=True, ownership_confirmed=True)
            first = await service.sync("candidate-sync")
            before_cache = len(requests)
            second = await service.sync("candidate-sync")
            assert len(requests) == before_cache
            return first, second

    first, second = asyncio.run(run())
    assert first == {"status": "synchronized", "repositories": 1, "contributions": 3}
    assert second == {"status": "fresh", "repositories": 1, "contributions": 0}
    with runtime.factory() as session:
        assert session.scalar(select(func.count(GitHubRepository.id))) == 1
        assert session.scalar(select(func.count(GitHubContribution.id))) == 3
        analysis = session.scalar(select(RepositoryAnalysis))
        assert analysis is not None
        assert analysis.signals["fastapi_implementation"] is True


def test_candidate_can_reconcile_and_correct_claim_findings(runtime) -> None:
    with runtime.factory.begin() as session:
        candidate = Candidate(id="candidate-reconcile")
        session.add(candidate)
        session.flush()
        document = SourceDocument(
            candidate_id=candidate.id,
            source_type="candidate_input",
            original_name="fixture",
            storage_key="fixture-reconcile",
            sha256="f" * 64,
            mime_type="text/plain",
            byte_size=1,
            extractor_name="fixture",
            extractor_version="1",
            extraction_status="succeeded",
            extracted_text="fixture",
        )
        session.add(document)
        session.flush()
        fragment = SourceFragment(
            source_document_id=document.id,
            source_text="Developed a FastAPI backend.",
            verification_status="resume_extracted",
        )
        session.add(fragment)
        session.flush()
        version = ProfileVersion(
            candidate_id=candidate.id,
            version_number=1,
            source_document_id=document.id,
            semantic_hash="a" * 64,
        )
        session.add(version)
        session.flush()
        candidate.current_profile_version_id = version.id
        entity = ProfileEntity(
            profile_version_id=version.id,
            entity_type="project",
            identity_key="fastapi-project",
            source_fragment_id=fragment.id,
        )
        session.add(entity)
        session.flush()
        session.add(
            EntityStatement(
                entity_id=entity.id,
                statement_type="description",
                text="Developed a FastAPI backend.",
                source_fragment_id=fragment.id,
            )
        )
        session.add(
            GitHubProfile(
                candidate_id=candidate.id,
                username="alice",
                profile_url="https://github.com/alice",
                analysis_authorized=True,
                enabled=True,
                ownership_status="unverified",
            )
        )
    service = GitHubService(runtime.factory)
    [finding] = service.reconcile_claims("candidate-reconcile")
    assert finding["classification"] == "unverified"
    assert "ownership is unconfirmed" in finding["explanation"]
    corrected = service.correct_claim(
        "candidate-reconcile",
        finding["id"],
        classification="partially_supported",
        note="Private work also supports this claim.",
    )
    assert corrected["candidate_correction"] == "partially_supported"
    assert corrected["candidate_note"] == "Private work also supports this claim."
    with runtime.factory() as session:
        assert session.scalar(select(func.count(ClaimReconciliation.id))) == 1
