from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

VerificationStatus = Literal[
    "resume_extracted",
    "candidate_confirmed",
    "source_verified",
    "unverified",
    "disputed",
    "unknown",
]
EvidenceClassification = Literal[
    "direct", "partial", "transferable", "candidate_confirmed", "unverified", "unknown"
]


class ExtractedLink(BaseModel):
    url: str
    page_number: int


class ExtractedDocument(BaseModel):
    text: str
    pages: list[str]
    links: list[ExtractedLink]
    page_count: int
    sha256: str
    byte_size: int
    warnings: list[str] = Field(default_factory=list)


class ParsedEntity(BaseModel):
    entity_type: Literal["experience", "project", "education", "contribution", "achievement"]
    identity_key: str
    title: str
    section: str
    data: dict[str, Any]
    statements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    source_url: str | None = None
    verification_status: VerificationStatus = "resume_extracted"


class ParsedSkill(BaseModel):
    canonical_name: str
    category: str
    original: str


class ParsedProfile(BaseModel):
    name: str | None = None
    summary: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    entities: list[ParsedEntity] = Field(default_factory=list)
    skills: list[ParsedSkill] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ValidationItem(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    entity_id: str | None = None
    field: str | None = None
    suggested_action: str | None = None


class CompletenessReport(BaseModel):
    candidate_id: str
    profile_version: int
    completeness_score: float
    items: list[ValidationItem]
    created_at: datetime


class IngestionResult(BaseModel):
    candidate_id: str
    profile_version_id: str
    version_number: int
    semantic_noop: bool
    entity_count: int
    skill_count: int
    evidence_count: int
    validation: CompletenessReport
