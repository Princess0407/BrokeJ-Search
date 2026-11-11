from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from brokej_search.core.config import Settings
from brokej_search.core.exceptions import NotFoundError, SourceBusyError
from brokej_search.database.models import (
    DeduplicationDecision,
    DiscoveryRun,
    DiscoverySource,
    Job,
    JobFieldObservation,
    JobLifecycleEvent,
    JobLocation,
    JobSkillRequirement,
    JobSourceAppearance,
    RetryItem,
    SourceCheckpoint,
    SourceLease,
    SourceRun,
    utcnow,
)
from brokej_search.discovery.connectors import AshbyConnector, GreenhouseConnector, LeverConnector
from brokej_search.discovery.connectors.base import JobConnector
from brokej_search.discovery.deduplication import canonicalize_url, evaluate, normalize_text
from brokej_search.discovery.schemas import DiscoverySummary, JobObservation, SourceCreate

CONNECTORS: dict[str, type[JobConnector]] = {
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "ashby": AshbyConnector,
}


class DiscoveryService:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings

    def add_source(self, value: SourceCreate) -> str:
        if value.connector_type not in CONNECTORS:
            raise ValueError(f"Unsupported connector: {value.connector_type}")
        with self.factory() as session, session.begin():
            existing = session.scalar(
                select(DiscoverySource).where(DiscoverySource.name == value.name)
            )
            if existing:
                raise ValueError(f"Source already exists: {value.name}")
            source = DiscoverySource(**value.model_dump())
            session.add(source)
            session.flush()
            return source.id

    def list_sources(self) -> list[dict[str, Any]]:
        with self.factory() as session:
            return [
                {
                    "id": source.id,
                    "name": source.name,
                    "connector_type": source.connector_type,
                    "board_identifier": source.board_identifier,
                    "company_name": source.company_name,
                    "enabled": source.enabled,
                    "last_attempted_at": source.last_attempted_at.isoformat()
                    if source.last_attempted_at
                    else None,
                    "last_successful_at": source.last_successful_at.isoformat()
                    if source.last_successful_at
                    else None,
                }
                for source in session.scalars(
                    select(DiscoverySource).order_by(DiscoverySource.name)
                )
            ]

    def set_source_enabled(self, source_id: str, enabled: bool) -> None:
        with self.factory() as session, session.begin():
            source = session.get(DiscoverySource, source_id)
            if not source:
                raise NotFoundError("Discovery source not found")
            source.enabled = enabled

    async def run(
        self,
        source_ids: list[str] | None = None,
        trigger: str = "manual",
        connector_overrides: dict[str, JobConnector] | None = None,
    ) -> DiscoverySummary:
        connector_overrides = connector_overrides or {}
        with self.factory() as session, session.begin():
            query = select(DiscoverySource).where(DiscoverySource.enabled.is_(True))
            if source_ids:
                query = query.where(DiscoverySource.id.in_(source_ids))
            sources = list(session.scalars(query.order_by(DiscoverySource.name)))
            run = DiscoveryRun(
                trigger=trigger, status="running", configuration={"source_ids": source_ids}
            )
            session.add(run)
            session.flush()
            run_id = run.id

        totals = {"succeeded": 0, "failed": 0, "fetched": 0, "created": 0, "updated": 0}
        for detached_source in sources:
            try:
                result = await self._run_source(
                    run_id, detached_source.id, connector_overrides.get(detached_source.id)
                )
                totals["succeeded"] += 1
                for key in ("fetched", "created", "updated"):
                    totals[key] += result[key]
            except Exception:
                totals["failed"] += 1

        status = (
            "succeeded"
            if not totals["failed"]
            else ("failed" if not totals["succeeded"] else "partial")
        )
        with self.factory() as session, session.begin():
            current_run = session.get(DiscoveryRun, run_id)
            assert current_run is not None
            current_run.status = status
            current_run.completed_at = utcnow()
        return DiscoverySummary(
            run_id=run_id,
            status=status,
            sources_succeeded=totals["succeeded"],
            sources_failed=totals["failed"],
            fetched=totals["fetched"],
            created=totals["created"],
            updated=totals["updated"],
        )

    async def run_due_retries(
        self, connector_overrides: dict[str, JobConnector] | None = None
    ) -> DiscoverySummary | None:
        with self.factory() as session:
            source_ids = list(
                session.scalars(
                    select(RetryItem.source_id)
                    .where(
                        RetryItem.status == "pending",
                        RetryItem.next_attempt_at <= utcnow(),
                    )
                    .distinct()
                )
            )
        if not source_ids:
            return None
        return await self.run(
            source_ids=source_ids,
            trigger="retry",
            connector_overrides=connector_overrides,
        )

    async def _run_source(
        self, run_id: str, source_id: str, override: JobConnector | None
    ) -> dict[str, int]:
        owner = str(uuid.uuid4())
        with self.factory() as session, session.begin():
            source = session.get(DiscoverySource, source_id)
            if not source:
                raise NotFoundError("Discovery source not found")
            self._acquire_lease(session, source_id, owner)
            source.last_attempted_at = utcnow()
            source_run = SourceRun(discovery_run_id=run_id, source_id=source_id, status="running")
            session.add(source_run)
            session.flush()
            source_run_id = source_run.id
            checkpoint = session.get(SourceCheckpoint, source_id)
            checkpoint_value = dict(checkpoint.value) if checkpoint else None
            board_identifier = source.board_identifier
            company_name = source.company_name
            source_config = dict(source.config)
            connector_type = source.connector_type

        seen_ids: set[str] = set()
        counts = {"fetched": 0, "created": 0, "updated": 0}
        client: httpx.AsyncClient | None = None
        try:
            connector = override
            if connector is None:
                client = httpx.AsyncClient(
                    timeout=self.settings.http_timeout_seconds,
                    headers={"User-Agent": self.settings.discovery_user_agent},
                    follow_redirects=True,
                )
                connector_class = CONNECTORS[connector_type]
                connector = connector_class(
                    client,
                    board_identifier,
                    company_name,
                    source_config,
                )
            async for page in connector.fetch(checkpoint_value):
                with self.factory() as session, session.begin():
                    for observation in page.jobs:
                        seen_ids.add(observation.source_job_id)
                        if not self._matches_config(observation, source_config):
                            continue
                        action = self._upsert_observation(session, source_id, observation)
                        counts["fetched"] += 1
                        counts[action] += 1
                    state = session.get(SourceCheckpoint, source_id)
                    if state is None:
                        state = SourceCheckpoint(source_id=source_id)
                        session.add(state)
                    state.value = page.checkpoint
                    state.response_hash = page.response_hash
                    state.etag = page.etag
                    state.last_modified = page.last_modified
                checkpoint_value = page.checkpoint
            with self.factory() as session, session.begin():
                self._mark_missing(session, source_id, seen_ids)
                source = session.get(DiscoverySource, source_id)
                completed_source_run = session.get(SourceRun, source_run_id)
                assert source and completed_source_run
                source.last_successful_at = utcnow()
                source.next_due_at = utcnow() + timedelta(
                    minutes=self.settings.discovery_interval_minutes
                )
                completed_source_run.status = "succeeded"
                completed_source_run.fetched_count = counts["fetched"]
                completed_source_run.created_count = counts["created"]
                completed_source_run.updated_count = counts["updated"]
                completed_source_run.completed_at = utcnow()
                for completed_retry in session.scalars(
                    select(RetryItem).where(
                        RetryItem.source_id == source_id,
                        RetryItem.status == "pending",
                    )
                ):
                    completed_retry.status = "succeeded"
                self._release_lease(session, source_id, owner)
            return counts
        except Exception as exc:
            with self.factory() as session, session.begin():
                failed_source_run = session.get(SourceRun, source_run_id)
                if failed_source_run:
                    failed_source_run.status = "failed"
                    failed_source_run.error_code = getattr(exc, "code", type(exc).__name__)
                    failed_source_run.error_message = str(exc)[:500]
                    failed_source_run.completed_at = utcnow()
                pending_retry = session.scalar(
                    select(RetryItem).where(
                        RetryItem.source_id == source_id,
                        RetryItem.status == "pending",
                    )
                )
                if pending_retry:
                    pending_retry.source_run_id = source_run_id
                    pending_retry.attempt_count += 1
                    pending_retry.next_attempt_at = utcnow() + timedelta(
                        minutes=min(60, 5 * (2 ** (pending_retry.attempt_count - 1)))
                    )
                    pending_retry.last_error_code = getattr(exc, "code", type(exc).__name__)
                else:
                    session.add(
                        RetryItem(
                            source_id=source_id,
                            source_run_id=source_run_id,
                            failure_category=type(exc).__name__,
                            next_attempt_at=utcnow() + timedelta(minutes=5),
                            last_error_code=getattr(exc, "code", type(exc).__name__),
                        )
                    )
                self._release_lease(session, source_id, owner)
            raise
        finally:
            if client:
                await client.aclose()

    @staticmethod
    def _matches_config(observation: JobObservation, config: dict[str, Any]) -> bool:
        keywords = [str(value).casefold() for value in config.get("search_keywords", [])]
        searchable = f"{observation.title} {observation.description_text}".casefold()
        if keywords and not any(keyword in searchable for keyword in keywords):
            return False
        locations = [str(value).casefold() for value in config.get("locations", [])]
        observed_locations = " ".join(observation.locations).casefold()
        if locations and not any(location in observed_locations for location in locations):
            return False
        arrangements = set(config.get("work_arrangements", []))
        if arrangements and observation.work_arrangement not in arrangements:
            return False
        employment_types = set(config.get("employment_types", []))
        return not employment_types or observation.employment_type in employment_types

    def _acquire_lease(self, session: Session, source_id: str, owner: str) -> None:
        now = utcnow()
        lease = session.get(SourceLease, source_id)
        if lease:
            expiry = lease.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry > now and lease.owner_token != owner:
                raise SourceBusyError("A discovery run is already active for this source")
            lease.owner_token = owner
            lease.expires_at = now + timedelta(minutes=10)
        else:
            session.add(
                SourceLease(
                    source_id=source_id, owner_token=owner, expires_at=now + timedelta(minutes=10)
                )
            )

    @staticmethod
    def _release_lease(session: Session, source_id: str, owner: str) -> None:
        lease = session.get(SourceLease, source_id)
        if lease and lease.owner_token == owner:
            session.delete(lease)

    def _upsert_observation(
        self, session: Session, source_id: str, observation: JobObservation
    ) -> str:
        appearance = session.scalar(
            select(JobSourceAppearance).where(
                JobSourceAppearance.source_id == source_id,
                JobSourceAppearance.source_job_id == observation.source_job_id,
            )
        )
        payload_hash = hashlib.sha256(
            json.dumps(observation.raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = utcnow()
        if appearance:
            job = session.get(Job, appearance.job_id)
            assert job is not None
            appearance.last_seen_at = now
            appearance.last_verified_at = now
            appearance.missing_successful_checks = 0
            job.last_seen_at = now
            job.last_verified_at = now
            if appearance.payload_sha256 != payload_hash:
                appearance.raw_payload = observation.raw
                appearance.payload_sha256 = payload_hash
                appearance.field_origins = observation.field_origins
                self._apply_observation(session, job, observation)
                self._replace_field_observations(session, appearance, observation)
            if job.status in {"unavailable", "expired"}:
                self._transition(session, job, "active", "source_reappeared")
            return "updated"

        normalized_company = normalize_text(observation.company_name)
        normalized_title = normalize_text(observation.title)
        observed_url = canonicalize_url(observation.application_url)
        candidate_conditions = [Job.normalized_company == normalized_company]
        if observed_url:
            candidate_conditions.append(Job.canonical_application_url == observed_url)
        candidates = list(session.scalars(select(Job).where(or_(*candidate_conditions)).limit(100)))
        best_job: Job | None = None
        best_result = None
        for candidate in candidates:
            result = evaluate(candidate, observation)
            if best_result is None or result.confidence > best_result.confidence:
                best_job, best_result = candidate, result
        if best_result and best_result.outcome == "merge":
            job = best_job
            assert job is not None
            session.add(
                DeduplicationDecision(
                    candidate_job_id=job.id,
                    matched_job_id=job.id,
                    engine_version="1",
                    signals=best_result.signals,
                    confidence=best_result.confidence,
                    outcome="merge",
                )
            )
        else:
            status = (
                "potential_duplicate"
                if best_result and best_result.outcome == "potential_duplicate"
                else "active"
            )
            job = Job(
                title=observation.title,
                normalized_title=normalized_title,
                company_name=observation.company_name,
                normalized_company=normalized_company,
                company_website=observation.company_website,
                description_text=observation.description_text,
                description_html=observation.description_html,
                listing_url=observation.listing_url,
                application_url=observation.application_url,
                canonical_application_url=canonicalize_url(observation.application_url),
                locations=observation.locations,
                work_arrangement=observation.work_arrangement,
                employment_type=observation.employment_type,
                opportunity_type=observation.opportunity_type,
                required_skills=observation.required_skills,
                preferred_skills=observation.preferred_skills,
                experience_requirements=observation.experience_requirements,
                education_requirements=observation.education_requirements,
                graduation_year_restrictions=observation.graduation_year_restrictions,
                compensation=observation.compensation,
                posting_date=observation.posting_date,
                application_deadline=observation.application_deadline,
                status=status,
                last_verified_at=now,
            )
            session.add(job)
            session.flush()
            self._replace_job_details(session, job, observation)
            session.add(
                JobLifecycleEvent(
                    job_id=job.id, old_status=None, new_status=status, reason="discovered"
                )
            )
            if best_job and best_result:
                session.add(
                    DeduplicationDecision(
                        candidate_job_id=job.id,
                        matched_job_id=best_job.id,
                        engine_version="1",
                        signals=best_result.signals,
                        confidence=best_result.confidence,
                        outcome=best_result.outcome,
                    )
                )
        assert job is not None
        appearance = JobSourceAppearance(
            job_id=job.id,
            source_id=source_id,
            source_job_id=observation.source_job_id,
            listing_url=observation.listing_url,
            application_url=observation.application_url,
            source_status="active",
            raw_payload=observation.raw,
            field_origins=observation.field_origins,
            payload_sha256=payload_hash,
            last_verified_at=now,
        )
        session.add(appearance)
        session.flush()
        self._replace_field_observations(session, appearance, observation)
        return "created" if not best_result or best_result.outcome != "merge" else "updated"

    def _apply_observation(self, session: Session, job: Job, value: JobObservation) -> None:
        job.title = value.title
        job.normalized_title = normalize_text(value.title)
        job.description_text = value.description_text
        job.description_html = value.description_html
        job.locations = value.locations
        job.work_arrangement = value.work_arrangement
        job.employment_type = value.employment_type
        job.opportunity_type = value.opportunity_type
        job.compensation = value.compensation
        job.posting_date = value.posting_date
        job.application_deadline = value.application_deadline
        self._replace_job_details(session, job, value)

    @staticmethod
    def _replace_job_details(session: Session, job: Job, value: JobObservation) -> None:
        session.execute(delete(JobLocation).where(JobLocation.job_id == job.id))
        session.execute(delete(JobSkillRequirement).where(JobSkillRequirement.job_id == job.id))
        for location in value.locations:
            session.add(
                JobLocation(
                    job_id=job.id,
                    original=location,
                    normalized=normalize_text(location),
                    remote_scope=location if "remote" in location.casefold() else None,
                )
            )
        for level, names in (
            ("required", value.required_skills),
            ("preferred", value.preferred_skills),
        ):
            for name in names:
                session.add(
                    JobSkillRequirement(
                        job_id=job.id,
                        skill_name=name,
                        requirement_level=level,
                        origin="parser_extracted",
                    )
                )

    @staticmethod
    def _replace_field_observations(
        session: Session,
        appearance: JobSourceAppearance,
        value: JobObservation,
    ) -> None:
        session.execute(
            delete(JobFieldObservation).where(JobFieldObservation.appearance_id == appearance.id)
        )
        serialized = value.model_dump(mode="json")
        for field_name, origin in value.field_origins.items():
            session.add(
                JobFieldObservation(
                    appearance_id=appearance.id,
                    field_name=field_name,
                    value_json=serialized.get(field_name),
                    origin=origin,
                    extractor_name=(
                        "connector_normalizer" if origin == "parser_extracted" else None
                    ),
                    extractor_version="1" if origin == "parser_extracted" else None,
                    source_path=field_name,
                )
            )

    def _mark_missing(self, session: Session, source_id: str, seen_ids: set[str]) -> None:
        appearances = list(
            session.scalars(
                select(JobSourceAppearance).where(JobSourceAppearance.source_id == source_id)
            )
        )
        affected_jobs: set[str] = set()
        for appearance in appearances:
            if appearance.source_job_id in seen_ids:
                continue
            appearance.missing_successful_checks += 1
            affected_jobs.add(appearance.job_id)
            if appearance.missing_successful_checks >= 2:
                appearance.source_status = "unavailable"
        for job_id in affected_jobs:
            job = session.get(Job, job_id)
            if not job or job.status == "archived":
                continue
            all_missing = all(item.missing_successful_checks >= 2 for item in job.appearances)
            if all_missing:
                self._transition(session, job, "expired", "all_sources_missing_twice")

    @staticmethod
    def _transition(session: Session, job: Job, new_status: str, reason: str) -> None:
        if job.status == new_status:
            return
        old_status = job.status
        job.status = new_status
        session.add(
            JobLifecycleEvent(
                job_id=job.id,
                old_status=old_status,
                new_status=new_status,
                reason=reason,
            )
        )

    def list_jobs(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.factory() as session:
            query = select(Job).order_by(Job.first_seen_at.desc()).limit(min(limit, 500))
            if status:
                query = query.where(Job.status == status)
            return [
                self._job_dict(job, include_description=False) for job in session.scalars(query)
            ]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.factory() as session:
            job = session.get(Job, job_id)
            if not job:
                raise NotFoundError("Job not found")
            return self._job_dict(job, include_description=True)

    @staticmethod
    def _job_dict(job: Job, include_description: bool) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": job.id,
            "title": job.title,
            "company": job.company_name,
            "locations": job.locations,
            "work_arrangement": job.work_arrangement,
            "employment_type": job.employment_type,
            "opportunity_type": job.opportunity_type,
            "listing_url": job.listing_url,
            "application_url": job.application_url,
            "status": job.status,
            "first_seen_at": job.first_seen_at.isoformat(),
            "last_seen_at": job.last_seen_at.isoformat(),
            "source_count": len(job.appearances),
        }
        if include_description:
            value["description"] = job.description_text
            value["compensation"] = job.compensation
            value["sources"] = [
                {
                    "source_id": appearance.source_id,
                    "source_job_id": appearance.source_job_id,
                    "listing_url": appearance.listing_url,
                    "first_seen_at": appearance.first_seen_at.isoformat(),
                    "last_seen_at": appearance.last_seen_at.isoformat(),
                }
                for appearance in job.appearances
            ]
        return value

    def run_status(self, run_id: str) -> dict[str, Any]:
        with self.factory() as session:
            run = session.get(DiscoveryRun, run_id)
            if not run:
                raise NotFoundError("Discovery run not found")
            return {
                "id": run.id,
                "trigger": run.trigger,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "sources": [
                    {
                        "source_id": source_run.source_id,
                        "status": source_run.status,
                        "fetched": source_run.fetched_count,
                        "created": source_run.created_count,
                        "updated": source_run.updated_count,
                        "error_code": source_run.error_code,
                    }
                    for source_run in run.source_runs
                ],
            }
