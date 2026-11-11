from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from brokej_search.core.exceptions import BrokeJError, NotFoundError
from brokej_search.discovery.schemas import SourceCreate
from brokej_search.runtime import Runtime, create_runtime


class IngestRequest(BaseModel):
    resume_path: str


class GitHubProfileRequest(BaseModel):
    username_or_url: str
    authorized: bool
    ownership_confirmed: bool = False


class ClaimCorrectionRequest(BaseModel):
    classification: str | None = None
    note: str = ""


def create_app(runtime: Runtime | None = None) -> FastAPI:
    runtime = runtime or create_runtime()
    app = FastAPI(title="BrokeJ-Search API", version="0.1.0")

    @app.exception_handler(BrokeJError)
    async def handle_domain_error(_request: Any, exc: BrokeJError) -> Any:
        status = 404 if isinstance(exc, NotFoundError) else 400
        return __import__("fastapi").responses.JSONResponse(
            status_code=status,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        try:
            with runtime.factory() as session:
                session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ready"}

    @app.get("/candidates/{candidate_id}/profile")
    def profile(candidate_id: str) -> dict[str, Any]:
        return runtime.profiles.get_profile(candidate_id, include_private=False)

    @app.get("/candidates/{candidate_id}/completeness")
    def completeness(candidate_id: str) -> dict[str, Any]:
        return runtime.profiles.validate(candidate_id).model_dump(mode="json")

    @app.get("/candidates/{candidate_id}/skills/{skill_name}/evidence")
    def evidence(candidate_id: str, skill_name: str) -> list[dict[str, Any]]:
        return runtime.profiles.evidence_for_skill(candidate_id, skill_name)

    @app.post("/candidates/{candidate_id}/ingestions")
    def ingest(candidate_id: str, request: IngestRequest) -> dict[str, Any]:
        return runtime.profiles.ingest_resume(candidate_id, Path(request.resume_path)).model_dump(
            mode="json"
        )

    @app.post("/discovery/sources", status_code=201)
    def add_source(source: SourceCreate) -> dict[str, str]:
        return {"id": runtime.discovery.add_source(source)}

    @app.get("/discovery/sources")
    def sources() -> list[dict[str, Any]]:
        return runtime.discovery.list_sources()

    @app.post("/discovery/runs")
    async def run_discovery(
        source_id: Annotated[list[str] | None, Query()] = None,
    ) -> dict[str, Any]:
        return (await runtime.discovery.run(source_id)).model_dump(mode="json")

    @app.get("/discovery/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, Any]:
        return runtime.discovery.run_status(run_id)

    @app.get("/jobs")
    def jobs(
        status: str | None = None, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        return runtime.discovery.list_jobs(status=status, limit=limit)

    @app.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        return runtime.discovery.get_job(job_id)

    @app.get("/jobs/{job_id}/requirements")
    def requirements(job_id: str) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.evaluation.decompose_job(job_id)]

    @app.post("/candidates/{candidate_id}/jobs/{job_id}/assessment")
    def assess(candidate_id: str, job_id: str) -> dict[str, Any]:
        return runtime.evaluation.assess(candidate_id, job_id).model_dump(mode="json")

    @app.put("/candidates/{candidate_id}/github")
    def configure_github(candidate_id: str, request: GitHubProfileRequest) -> dict[str, Any]:
        return runtime.github.configure(
            candidate_id,
            request.username_or_url,
            authorized=request.authorized,
            ownership_confirmed=request.ownership_confirmed,
        )

    @app.delete("/candidates/{candidate_id}/github", status_code=204)
    def disable_github(candidate_id: str) -> None:
        runtime.github.disable(candidate_id)

    @app.post("/candidates/{candidate_id}/github/reconciliations")
    def reconcile_github_claims(candidate_id: str) -> list[dict[str, Any]]:
        return runtime.github.reconcile_claims(candidate_id)

    @app.patch("/candidates/{candidate_id}/github/reconciliations/{reconciliation_id}")
    def correct_github_claim(
        candidate_id: str,
        reconciliation_id: str,
        request: ClaimCorrectionRequest,
    ) -> dict[str, Any]:
        return runtime.github.correct_claim(
            candidate_id,
            reconciliation_id,
            classification=request.classification,
            note=request.note,
        )

    return app


app = create_app()
