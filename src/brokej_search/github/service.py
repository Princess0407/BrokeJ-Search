from __future__ import annotations

import base64
import re
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from brokej_search.core.exceptions import NotFoundError
from brokej_search.database.models import (
    Candidate,
    ClaimReconciliation,
    EntityStatement,
    GitHubContribution,
    GitHubProfile,
    GitHubRepository,
    ProfileEntity,
    RepositoryAnalysis,
    utcnow,
)
from brokej_search.github.analysis import analyze_repository, reconcile_claim
from brokej_search.github.client import GitHubClient

_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_SELECTED_NAMES = {
    "dockerfile",
    "go.mod",
    "main.go",
    "main.py",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}


class GitHubService:
    def __init__(self, factory: sessionmaker[Session], client: GitHubClient | None = None) -> None:
        self.factory = factory
        self.client = client

    def configure(
        self,
        candidate_id: str,
        username_or_url: str,
        *,
        authorized: bool,
        ownership_confirmed: bool = False,
    ) -> dict[str, Any]:
        username = parse_username(username_or_url)
        with self.factory.begin() as session:
            if not session.get(Candidate, candidate_id):
                raise NotFoundError("Candidate not found")
            profile = session.scalar(
                select(GitHubProfile).where(GitHubProfile.candidate_id == candidate_id)
            )
            if not profile:
                profile = GitHubProfile(
                    candidate_id=candidate_id,
                    username=username,
                    profile_url=f"https://github.com/{username}",
                )
            profile.username = username
            profile.profile_url = f"https://github.com/{username}"
            profile.analysis_authorized = authorized
            profile.enabled = authorized
            profile.ownership_status = (
                "candidate_confirmed" if ownership_confirmed else "unverified"
            )
            profile.provenance = {"source": "candidate_input"}
            session.add(profile)
            session.flush()
            return self._profile_dict(profile)

    def disable(self, candidate_id: str) -> None:
        with self.factory.begin() as session:
            profile = session.scalar(
                select(GitHubProfile).where(GitHubProfile.candidate_id == candidate_id)
            )
            if profile:
                profile.enabled = False
                profile.analysis_authorized = False

    def reconcile_claims(self, candidate_id: str) -> list[dict[str, Any]]:
        with self.factory.begin() as session:
            candidate = session.get(Candidate, candidate_id)
            profile = session.scalar(
                select(GitHubProfile).where(GitHubProfile.candidate_id == candidate_id)
            )
            if (
                not candidate
                or not candidate.current_profile_version_id
                or not profile
                or not profile.enabled
                or not profile.analysis_authorized
            ):
                return []
            analyses = list(
                session.scalars(
                    select(RepositoryAnalysis)
                    .join(GitHubRepository)
                    .where(GitHubRepository.github_profile_id == profile.id)
                )
            )
            version_id = candidate.current_profile_version_id
            statements = list(
                session.execute(
                    select(EntityStatement, ProfileEntity)
                    .join(ProfileEntity, ProfileEntity.id == EntityStatement.entity_id)
                    .where(
                        ProfileEntity.profile_version_id == version_id,
                        ProfileEntity.entity_type.in_(["project", "experience", "contribution"]),
                    )
                )
            )
            output = []
            for statement, _entity in statements:
                classification, explanation = reconcile_claim(
                    statement.text,
                    [
                        {
                            "signals": analysis.signals,
                            "source_urls": analysis.source_urls,
                        }
                        for analysis in analyses
                    ],
                )
                if profile.ownership_status != "candidate_confirmed":
                    classification = "unverified"
                    explanation = (
                        "GitHub account ownership is unconfirmed; repository evidence is not "
                        "attributed to the candidate."
                    )
                existing = session.scalar(
                    select(ClaimReconciliation).where(
                        ClaimReconciliation.candidate_id == candidate_id,
                        ClaimReconciliation.profile_version_id == version_id,
                        ClaimReconciliation.claim == statement.text,
                    )
                )
                if not existing:
                    existing = ClaimReconciliation(
                        candidate_id=candidate_id,
                        profile_version_id=version_id,
                        claim=statement.text,
                    )
                existing.classification = classification
                existing.explanation = explanation
                existing.evidence = [
                    {"analysis_id": analysis.id, "source_urls": analysis.source_urls}
                    for analysis in analyses
                ]
                session.add(existing)
                session.flush()
                output.append(self._reconciliation_dict(existing))
            return output

    def correct_claim(
        self, candidate_id: str, reconciliation_id: str, *, classification: str | None, note: str
    ) -> dict[str, Any]:
        allowed = {
            "supported",
            "partially_supported",
            "self_reported_only",
            "unverified",
            "contradictory",
            "not_applicable",
        }
        if classification is not None and classification not in allowed:
            raise ValueError("Unsupported claim correction")
        with self.factory.begin() as session:
            row = session.scalar(
                select(ClaimReconciliation).where(
                    ClaimReconciliation.id == reconciliation_id,
                    ClaimReconciliation.candidate_id == candidate_id,
                )
            )
            if not row:
                raise NotFoundError("Claim reconciliation not found")
            row.candidate_correction = classification
            row.candidate_note = note.strip() or None
            row.corrected_at = utcnow()
            session.flush()
            return self._reconciliation_dict(row)

    @staticmethod
    def _reconciliation_dict(row: ClaimReconciliation) -> dict[str, Any]:
        return {
            "id": row.id,
            "claim": row.claim,
            "classification": row.classification,
            "explanation": row.explanation,
            "evidence": row.evidence,
            "candidate_correction": row.candidate_correction,
            "candidate_note": row.candidate_note,
        }

    async def sync(self, candidate_id: str, *, force: bool = False) -> dict[str, Any]:
        with self.factory() as session:
            profile = session.scalar(
                select(GitHubProfile).where(GitHubProfile.candidate_id == candidate_id)
            )
            if not profile:
                raise NotFoundError("GitHub profile is not configured")
            if not profile.enabled or not profile.analysis_authorized:
                return {"status": "disabled", "repositories": 0, "contributions": 0}
            if (
                not force
                and profile.last_successful_sync_at
                and profile.last_successful_sync_at.replace(
                    tzinfo=profile.last_successful_sync_at.tzinfo or UTC
                )
                >= utcnow() - timedelta(hours=24)
            ):
                count = len(
                    session.scalars(
                        select(GitHubRepository).where(
                            GitHubRepository.github_profile_id == profile.id
                        )
                    ).all()
                )
                return {"status": "fresh", "repositories": count, "contributions": 0}
            profile_id, username, etag = profile.id, profile.username, profile.etag

        if not self.client:
            raise RuntimeError("GitHub client is not configured")

        user, user_headers = await self.client.get_json(f"/users/{username}", etag=etag)
        if user is None and not etag:
            raise NotFoundError("GitHub user not found")
        repos = await self.client.paginated(
            f"/users/{username}/repos",
            params={"type": "owner", "sort": "updated", "direction": "desc"},
            max_items=100,
        )
        analyzed = [
            await self._inspect_repository(repo) for repo in repos if not repo.get("private")
        ]
        contributions = await self._contributions(username)
        now = utcnow()
        with self.factory.begin() as session:
            profile = session.get(GitHubProfile, profile_id)
            assert profile is not None
            if user:
                profile.github_user_id = user.get("id")
            profile.etag = user_headers.get("etag", profile.etag)
            profile.last_checked_at = now
            profile.last_successful_sync_at = now
            for repo, analysis in analyzed:
                row = session.scalar(
                    select(GitHubRepository).where(
                        GitHubRepository.github_profile_id == profile.id,
                        GitHubRepository.github_repo_id == repo["id"],
                    )
                )
                if not row:
                    row = GitHubRepository(
                        github_profile_id=profile.id,
                        github_repo_id=repo["id"],
                        full_name=repo["full_name"],
                        html_url=repo["html_url"],
                    )
                row.full_name = repo["full_name"]
                row.html_url = repo["html_url"]
                row.description = repo.get("description")
                row.fork = bool(repo.get("fork"))
                row.archived = bool(repo.get("archived"))
                row.default_branch = repo.get("default_branch")
                row.languages = analysis.pop("languages")
                row.topics = repo.get("topics") or []
                row.repository_metadata = {
                    "size": repo.get("size"),
                    "visibility": repo.get("visibility", "public"),
                }
                row.repository_updated_at = parse_datetime(repo.get("updated_at"))
                row.checked_at = now
                session.add(row)
                session.flush()
                repository_existing = session.scalar(
                    select(RepositoryAnalysis).where(
                        RepositoryAnalysis.repository_id == row.id,
                        RepositoryAnalysis.analysis_version == analysis["analysis_version"],
                        RepositoryAnalysis.source_hash == analysis["source_hash"],
                    )
                )
                if not repository_existing:
                    session.add(
                        RepositoryAnalysis(
                            repository_id=row.id, source_urls=[row.html_url], **analysis
                        )
                    )
            for item in contributions:
                contribution_existing = session.scalar(
                    select(GitHubContribution).where(
                        GitHubContribution.github_profile_id == profile.id,
                        GitHubContribution.kind == item["kind"],
                        GitHubContribution.api_url == item["api_url"],
                    )
                )
                if not contribution_existing:
                    metadata = item.pop("metadata")
                    session.add(
                        GitHubContribution(
                            github_profile_id=profile.id,
                            contribution_metadata=metadata,
                            **item,
                        )
                    )
        self.reconcile_claims(candidate_id)
        return {
            "status": "synchronized",
            "repositories": len(analyzed),
            "contributions": len(contributions),
        }

    async def _inspect_repository(
        self, repo: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        client = self.client
        assert client is not None
        full_name = repo["full_name"]
        languages, _ = await client.get_json(f"/repos/{full_name}/languages")
        tree, _ = await client.get_json(
            f"/repos/{full_name}/git/trees/{repo.get('default_branch', 'HEAD')}",
            params={"recursive": "1"},
        )
        entries = tree.get("tree", []) if isinstance(tree, dict) else []
        paths = [
            item["path"]
            for item in entries[:2000]
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
        selected_paths = [
            path for path in paths if path.casefold().rsplit("/", 1)[-1] in _SELECTED_NAMES
        ][:8]
        selected: dict[str, str] = {}
        for path in selected_paths:
            payload, _ = await client.get_json(f"/repos/{full_name}/contents/{path}")
            content = decode_content(payload)
            if content is not None:
                selected[path] = content
        readme_payload, _ = await client.get_json(f"/repos/{full_name}/readme")
        readme = decode_content(readme_payload)
        analysis = analyze_repository(repo, paths, selected, readme)
        analysis["languages"] = languages if isinstance(languages, dict) else {}
        return repo, analysis

    async def _contributions(self, username: str) -> list[dict[str, Any]]:
        client = self.client
        assert client is not None
        output: list[dict[str, Any]] = []
        for kind, query in (
            ("pull_request", f"author:{username} type:pr"),
            ("issue", f"author:{username} type:issue"),
            ("review", f"reviewed-by:{username} type:pr"),
        ):
            payload, _ = await client.get_json(
                "/search/issues", params={"q": query, "per_page": 30}
            )
            for item in payload.get("items", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                output.append(
                    {
                        "repository_full_name": repository_from_api_url(item.get("repository_url")),
                        "kind": kind,
                        "api_url": item["url"],
                        "html_url": item.get("html_url"),
                        "state": item.get("state"),
                        "attribution_status": "api_attributed",
                        "occurred_at": parse_datetime(
                            item.get("closed_at") or item.get("created_at")
                        ),
                        "metadata": {
                            "number": item.get("number"),
                            "merged": item.get("pull_request", {}).get("merged_at") is not None,
                        },
                    }
                )
        return output

    @staticmethod
    def _profile_dict(profile: GitHubProfile) -> dict[str, Any]:
        return {
            "candidate_id": profile.candidate_id,
            "username": profile.username,
            "profile_url": profile.profile_url,
            "authorized": profile.analysis_authorized,
            "ownership_status": profile.ownership_status,
            "enabled": profile.enabled,
        }


def parse_username(value: str) -> str:
    candidate = value.strip().rstrip("/").rsplit("/", 1)[-1]
    if not _USERNAME.fullmatch(candidate):
        raise ValueError("Invalid GitHub username or profile URL")
    return candidate


def decode_content(payload: Any, max_bytes: int = 131_072) -> str | None:
    if (
        not isinstance(payload, dict)
        or payload.get("encoding") != "base64"
        or not isinstance(payload.get("content"), str)
    ):
        return None
    raw = base64.b64decode(payload["content"], validate=False)
    if len(raw) > max_bytes:
        return None
    return raw.decode("utf-8", errors="replace")


def parse_datetime(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def repository_from_api_url(value: Any) -> str | None:
    if not isinstance(value, str) or "/repos/" not in value:
        return None
    return value.split("/repos/", 1)[1]
