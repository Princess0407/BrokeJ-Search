from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from brokej_search.database.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    display_name: Mapped[str | None] = mapped_column(String(255))
    current_profile_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("profile_versions.id", name="fk_candidate_current_profile")
    )
    current_preference_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("preference_versions.id", name="fk_candidate_current_preferences")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("candidate_id", "sha256", "source_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="resume_pdf")
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extractor_name: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(String(32))
    extraction_status: Mapped[str] = mapped_column(String(32))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fragments: Mapped[list[SourceFragment]] = relationship(cascade="all, delete-orphan")


class SourceFragment(Base):
    __tablename__ = "source_fragments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(100))
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    extracted_value: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), default="resume_extracted")
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    parser_name: Mapped[str] = mapped_column(String(80))
    parser_version: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32), default="merge")
    status: Mapped[str] = mapped_column(String(32))
    profile_version_id: Mapped[str | None] = mapped_column(String(36))
    semantic_noop: Mapped[bool] = mapped_column(Boolean, default=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "version_number"),
        UniqueConstraint("candidate_id", "semantic_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("profile_versions.id"))
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("source_documents.id"))
    semantic_hash: Mapped[str] = mapped_column(String(64))
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[CandidateDetail | None] = relationship(cascade="all, delete-orphan")
    entities: Mapped[list[ProfileEntity]] = relationship(cascade="all, delete-orphan")
    skills: Mapped[list[ProfileSkill]] = relationship(cascade="all, delete-orphan")


class CandidateDetail(Base):
    __tablename__ = "candidate_details"
    profile_version_id: Mapped[str] = mapped_column(
        ForeignKey("profile_versions.id"), primary_key=True
    )
    professional_name: Mapped[str | None] = mapped_column(String(255))
    professional_summary: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(80))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    github_url: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[str] = mapped_column(String(32), default="resume_extracted")


class ProfileEntity(Base):
    __tablename__ = "profile_entities"
    __table_args__ = (UniqueConstraint("profile_version_id", "entity_type", "identity_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    identity_key: Mapped[str] = mapped_column(String(512))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    verification_status: Mapped[str] = mapped_column(String(32), default="resume_extracted")
    source_fragment_id: Mapped[str | None] = mapped_column(ForeignKey("source_fragments.id"))
    statements: Mapped[list[EntityStatement]] = relationship(cascade="all, delete-orphan")


class Experience(Base):
    __tablename__ = "experiences"
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), primary_key=True)
    organization: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    work_arrangement: Mapped[str | None] = mapped_column(String(32))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    date_precision: Mapped[str] = mapped_column(String(16), default="month")
    employment_type: Mapped[str | None] = mapped_column(String(32))


class Project(Base):
    __tablename__ = "projects"
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    short_description: Mapped[str | None] = mapped_column(Text)
    problem_addressed: Mapped[str | None] = mapped_column(Text)
    repository_url: Mapped[str | None] = mapped_column(Text)
    documentation_url: Mapped[str | None] = mapped_column(Text)


class Education(Base):
    __tablename__ = "education"
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), primary_key=True)
    institution: Mapped[str] = mapped_column(String(255))
    degree: Mapped[str | None] = mapped_column(String(255))
    discipline: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    expected_graduation: Mapped[bool] = mapped_column(Boolean, default=False)
    academic_details: Mapped[str | None] = mapped_column(Text)


class Contribution(Base):
    __tablename__ = "contributions"
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), primary_key=True)
    repository: Mapped[str] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(100))
    contribution_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    evidence_url: Mapped[str | None] = mapped_column(Text)


class Achievement(Base):
    __tablename__ = "achievements"
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    organization: Mapped[str | None] = mapped_column(String(255))
    achieved_year: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)


class EntityStatement(Base):
    __tablename__ = "entity_statements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), index=True)
    statement_type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    source_fragment_id: Mapped[str | None] = mapped_column(ForeignKey("source_fragments.id"))
    verification_status: Mapped[str] = mapped_column(String(32), default="resume_extracted")


class SkillCatalog(Base):
    __tablename__ = "skill_catalog"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)


class ProfileSkill(Base):
    __tablename__ = "profile_skills"
    __table_args__ = (UniqueConstraint("profile_version_id", "skill_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"), index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_catalog.id"), index=True)
    candidate_proficiency: Mapped[str | None] = mapped_column(String(80))
    verification_status: Mapped[str] = mapped_column(String(32), default="unverified")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog: Mapped[SkillCatalog] = relationship()
    evidence: Mapped[list[EvidenceEdge]] = relationship(cascade="all, delete-orphan")


class EvidenceEdge(Base):
    __tablename__ = "evidence_edges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_skill_id: Mapped[str] = mapped_column(ForeignKey("profile_skills.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("profile_entities.id"), index=True)
    statement_id: Mapped[str | None] = mapped_column(ForeignKey("entity_statements.id"))
    source_fragment_id: Mapped[str] = mapped_column(ForeignKey("source_fragments.id"))
    classification: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), default="resume_extracted")
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entity: Mapped[ProfileEntity] = relationship()
    statement: Mapped[EntityStatement | None] = relationship()


class PreferenceVersion(Base):
    __tablename__ = "preference_versions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "version_number"),
        UniqueConstraint("candidate_id", "semantic_hash"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("preference_versions.id"))
    semantic_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list[PreferenceItem]] = relationship(cascade="all, delete-orphan")


class PreferenceItem(Base):
    __tablename__ = "preference_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    preference_version_id: Mapped[str] = mapped_column(
        ForeignKey("preference_versions.id"), index=True
    )
    preference_type: Mapped[str] = mapped_column(String(60))
    value: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int | None] = mapped_column(Integer)
    is_hard_constraint: Mapped[bool | None] = mapped_column(Boolean)
    operator: Mapped[str | None] = mapped_column(String(20))
    unit: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str | None] = mapped_column(String(3))


class ValidationReport(Base):
    __tablename__ = "validation_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"))
    preference_version_id: Mapped[str | None] = mapped_column(ForeignKey("preference_versions.id"))
    validator_version: Mapped[str] = mapped_column(String(32))
    completeness_score: Mapped[float] = mapped_column(Float)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoverySource(Base):
    __tablename__ = "discovery_sources"
    __table_args__ = (UniqueConstraint("name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    connector_type: Mapped[str] = mapped_column(String(32), index=True)
    board_identifier: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"
    source_id: Mapped[str] = mapped_column(ForeignKey("discovery_sources.id"), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceLease(Base):
    __tablename__ = "source_leases"
    source_id: Mapped[str] = mapped_column(ForeignKey("discovery_sources.id"), primary_key=True)
    owner_token: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_runs: Mapped[list[SourceRun]] = relationship(cascade="all, delete-orphan")


class SourceRun(Base):
    __tablename__ = "source_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    discovery_run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("discovery_sources.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetryItem(Base):
    __tablename__ = "retry_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("discovery_sources.id"), index=True)
    source_run_id: Mapped[str | None] = mapped_column(ForeignKey("source_runs.id"))
    failure_category: Mapped[str] = mapped_column(String(80))
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_error_code: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('discovered','active','potential_duplicate',"
            "'expired','unavailable','archived')"
        ),
        Index("ix_jobs_company_title", "normalized_company", "normalized_title"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500))
    company_name: Mapped[str] = mapped_column(String(255))
    normalized_company: Mapped[str] = mapped_column(String(255))
    company_website: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str] = mapped_column(Text, default="")
    description_html: Mapped[str | None] = mapped_column(Text)
    listing_url: Mapped[str] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    canonical_application_url: Mapped[str | None] = mapped_column(Text, index=True)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_arrangement: Mapped[str] = mapped_column(String(20), default="unknown")
    employment_type: Mapped[str] = mapped_column(String(30), default="unknown")
    opportunity_type: Mapped[str] = mapped_column(String(30), default="unknown")
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience_requirements: Mapped[str | None] = mapped_column(Text)
    education_requirements: Mapped[str | None] = mapped_column(Text)
    graduation_year_restrictions: Mapped[str | None] = mapped_column(Text)
    compensation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    posting_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="discovered")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appearances: Mapped[list[JobSourceAppearance]] = relationship(cascade="all, delete-orphan")
    location_rows: Mapped[list[JobLocation]] = relationship(cascade="all, delete-orphan")
    skill_requirements: Mapped[list[JobSkillRequirement]] = relationship(
        cascade="all, delete-orphan"
    )


class JobLocation(Base):
    __tablename__ = "job_locations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    original: Mapped[str] = mapped_column(String(500))
    normalized: Mapped[str] = mapped_column(String(500))
    remote_scope: Mapped[str | None] = mapped_column(String(255))


class JobSkillRequirement(Base):
    __tablename__ = "job_skill_requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    skill_name: Mapped[str] = mapped_column(String(150))
    requirement_level: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(30))


class JobSourceAppearance(Base):
    __tablename__ = "job_source_appearances"
    __table_args__ = (UniqueConstraint("source_id", "source_job_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("discovery_sources.id"), index=True)
    source_job_id: Mapped[str] = mapped_column(String(500))
    listing_url: Mapped[str] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    source_status: Mapped[str | None] = mapped_column(String(40))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    field_origins: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    missing_successful_checks: Mapped[int] = mapped_column(Integer, default=0)
    observations: Mapped[list[JobFieldObservation]] = relationship(cascade="all, delete-orphan")


class JobFieldObservation(Base):
    __tablename__ = "job_field_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    appearance_id: Mapped[str] = mapped_column(ForeignKey("job_source_appearances.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(100))
    value_json: Mapped[Any] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String(30))
    extractor_name: Mapped[str | None] = mapped_column(String(80))
    extractor_version: Mapped[str | None] = mapped_column(String(32))
    source_path: Mapped[str | None] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeduplicationDecision(Base):
    __tablename__ = "deduplication_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    matched_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    engine_version: Mapped[str] = mapped_column(String(20))
    signals: Mapped[dict[str, Any]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    outcome: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobLifecycleEvent(Base):
    __tablename__ = "job_lifecycle_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubProfile(Base):
    __tablename__ = "github_profiles"
    __table_args__ = (UniqueConstraint("candidate_id"), UniqueConstraint("username"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    username: Mapped[str] = mapped_column(String(100))
    profile_url: Mapped[str] = mapped_column(Text)
    github_user_id: Mapped[int | None] = mapped_column(Integer)
    analysis_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    ownership_status: Mapped[str] = mapped_column(String(32), default="unverified")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GitHubRepository(Base):
    __tablename__ = "github_repositories"
    __table_args__ = (UniqueConstraint("github_profile_id", "github_repo_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    github_profile_id: Mapped[str] = mapped_column(ForeignKey("github_profiles.id"), index=True)
    github_repo_id: Mapped[int] = mapped_column(Integer)
    full_name: Mapped[str] = mapped_column(String(255))
    html_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    fork: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    default_branch: Mapped[str | None] = mapped_column(String(255))
    languages: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    repository_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    etag: Mapped[str | None] = mapped_column(String(255))
    repository_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubContribution(Base):
    __tablename__ = "github_contributions"
    __table_args__ = (UniqueConstraint("github_profile_id", "kind", "api_url"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    github_profile_id: Mapped[str] = mapped_column(ForeignKey("github_profiles.id"), index=True)
    repository_full_name: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    api_url: Mapped[str] = mapped_column(Text)
    html_url: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(32))
    attribution_status: Mapped[str] = mapped_column(String(32), default="uncertain")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contribution_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class RepositoryAnalysis(Base):
    __tablename__ = "repository_analyses"
    __table_args__ = (UniqueConstraint("repository_id", "analysis_version", "source_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repository_id: Mapped[str] = mapped_column(ForeignKey("github_repositories.id"), index=True)
    analysis_version: Mapped[str] = mapped_column(String(32))
    source_hash: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(40))
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimReconciliation(Base):
    __tablename__ = "claim_reconciliations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidate_correction: Mapped[str | None] = mapped_column(String(32))
    candidate_note: Mapped[str | None] = mapped_column(Text)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobRequirement(Base):
    __tablename__ = "job_requirements"
    __table_args__ = (UniqueConstraint("job_id", "source_hash", "requirement_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    requirement_key: Mapped[str] = mapped_column(String(64))
    original_text: Mapped[str] = mapped_column(Text)
    normalized_competency: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(40))
    criticality: Mapped[str] = mapped_column(String(32))
    mandatory_status: Mapped[str] = mapped_column(String(20))
    evidence_expected: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_confidence: Mapped[float] = mapped_column(Float)
    source_reference: Mapped[str] = mapped_column(String(255))
    extractor_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualificationAssessment(Base):
    __tablename__ = "qualification_assessments"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", "profile_version_id", "engine_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    profile_version_id: Mapped[str] = mapped_column(ForeignKey("profile_versions.id"))
    preference_version_id: Mapped[str | None] = mapped_column(ForeignKey("preference_versions.id"))
    engine_version: Mapped[str] = mapped_column(String(32))
    requirement_source_hash: Mapped[str] = mapped_column(String(64))
    scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSON)
    missing_requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unverified_claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    contradictions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RequirementEvidenceMatch(Base):
    __tablename__ = "requirement_evidence_matches"
    __table_args__ = (UniqueConstraint("assessment_id", "requirement_id", "evidence_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("qualification_assessments.id"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(ForeignKey("job_requirements.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    related_skill: Mapped[str | None] = mapped_column(String(255))
    relevant_dates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    classification: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(32))
    retrieval_confidence: Mapped[float] = mapped_column(Float)


class GrowthAssessment(Base):
    __tablename__ = "growth_assessments"
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("qualification_assessments.id"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(20))
    foundations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reasoning: Mapped[list[str]] = mapped_column(JSON, default=list)


class Recommendation(Base):
    __tablename__ = "recommendations"
    assessment_id: Mapped[str] = mapped_column(
        ForeignKey("qualification_assessments.id"), primary_key=True
    )
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    critic_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    benchmark_version: Mapped[str] = mapped_column(String(32), index=True)
    engine_version: Mapped[str] = mapped_column(String(32))
    case_count: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
