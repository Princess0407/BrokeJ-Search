from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RequirementCategory = Literal[
    "technical_skill",
    "programming_language",
    "framework_tool",
    "system_design_architecture",
    "responsibility",
    "experience",
    "education",
    "graduation_eligibility",
    "work_authorization",
    "location_work_arrangement",
    "other_eligibility",
]
Criticality = Literal[
    "hard_eligibility",
    "core_mandatory",
    "mandatory_but_ambiguous",
    "preferred",
    "trainable",
    "unknown",
]
MandatoryStatus = Literal["mandatory", "preferred", "unknown"]
EvidenceClassification = Literal[
    "direct",
    "partial",
    "transferable",
    "self_reported",
    "unverified",
    "unknown",
    "contradictory",
]
RecommendationOutcome = Literal[
    "priority_shortlist",
    "growth_opportunity",
    "manual_review",
    "do_not_prioritize",
    "ineligible",
]


class JobRequirementData(BaseModel):
    id: str
    original_text: str
    normalized_competency: str | None
    category: RequirementCategory
    criticality: Criticality
    mandatory_status: MandatoryStatus
    evidence_expected: list[str]
    extraction_confidence: float = Field(ge=0, le=1)
    source_reference: str


class RequirementSource(BaseModel):
    description: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirements: str | None = None
    education_requirements: str | None = None
    graduation_year_restrictions: str | None = None
    locations: list[str] = Field(default_factory=list)
    work_arrangement: str = "unknown"


class CandidateEvidence(BaseModel):
    evidence_id: str
    source: str
    supporting_description: str
    related_skill: str | None = None
    relevant_dates: dict[str, str | None] = Field(default_factory=dict)
    classification: EvidenceClassification
    verification_status: str
    retrieval_confidence: float = Field(ge=0, le=1)


class RequirementAssessment(BaseModel):
    requirement: JobRequirementData
    status: Literal["satisfied", "partial", "missing", "unknown", "failed"]
    evidence: list[CandidateEvidence] = Field(default_factory=list)
    reasoning: str


class ScoreDetail(BaseModel):
    value: float | None = Field(default=None, ge=0, le=1)
    status: Literal["measured", "unknown", "failed"]
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)


class EligibilityAssessment(BaseModel):
    status: Literal["passed", "failed", "unknown", "not_applicable"]
    requirements: list[RequirementAssessment] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    assessment_id: str
    candidate_id: str
    job_id: str
    outcome: RecommendationOutcome
    scores: dict[str, ScoreDetail]
    eligibility: EligibilityAssessment
    requirements: list[RequirementAssessment]
    growth_score: float = Field(ge=0, le=1)
    growth_band: Literal["low", "moderate", "high"]
    supporting_evidence: list[CandidateEvidence]
    missing_requirements: list[JobRequirementData]
    unverified_claims: list[CandidateEvidence]
    contradictory_evidence: list[CandidateEvidence]
    critic_flags: list[str]
    confidence: float = Field(ge=0, le=1)
    explanation: str
    assessed_at: datetime
