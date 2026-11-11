"""evidence based job evaluation

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=False),
        sa.Column("github_user_id", sa.Integer()),
        sa.Column("analysis_authorized", sa.Boolean(), nullable=False),
        sa.Column("ownership_status", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("etag", sa.String(255)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_github_profiles_candidate_id", "github_profiles", ["candidate_id"])
    op.create_table(
        "github_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "github_profile_id", sa.String(36), sa.ForeignKey("github_profiles.id"), nullable=False
        ),
        sa.Column("github_repo_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("fork", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("default_branch", sa.String(255)),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("etag", sa.String(255)),
        sa.Column("repository_updated_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("github_profile_id", "github_repo_id"),
    )
    op.create_index(
        "ix_github_repositories_github_profile_id", "github_repositories", ["github_profile_id"]
    )
    op.create_table(
        "github_contributions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "github_profile_id", sa.String(36), sa.ForeignKey("github_profiles.id"), nullable=False
        ),
        sa.Column("repository_full_name", sa.String(255)),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("api_url", sa.Text(), nullable=False),
        sa.Column("html_url", sa.Text()),
        sa.Column("state", sa.String(32)),
        sa.Column("attribution_status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.UniqueConstraint("github_profile_id", "kind", "api_url"),
    )
    op.create_index(
        "ix_github_contributions_github_profile_id", "github_contributions", ["github_profile_id"]
    )
    op.create_table(
        "repository_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id", sa.String(36), sa.ForeignKey("github_repositories.id"), nullable=False
        ),
        sa.Column("analysis_version", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.Text()),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("source_urls", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_id", "analysis_version", "source_hash"),
    )
    op.create_index(
        "ix_repository_analyses_repository_id", "repository_analyses", ["repository_id"]
    )
    op.create_table(
        "claim_reconciliations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column(
            "profile_version_id",
            sa.String(36),
            sa.ForeignKey("profile_versions.id"),
            nullable=False,
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("candidate_correction", sa.String(32)),
        sa.Column("candidate_note", sa.Text()),
        sa.Column("corrected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_claim_reconciliations_candidate_id", "claim_reconciliations", ["candidate_id"]
    )
    op.create_index(
        "ix_claim_reconciliations_profile_version_id",
        "claim_reconciliations",
        ["profile_version_id"],
    )
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("requirement_key", sa.String(64), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("normalized_competency", sa.String(255)),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("criticality", sa.String(32), nullable=False),
        sa.Column("mandatory_status", sa.String(20), nullable=False),
        sa.Column("evidence_expected", sa.JSON(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("extractor_version", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "source_hash", "requirement_key"),
    )
    op.create_index("ix_job_requirements_job_id", "job_requirements", ["job_id"])
    op.create_index("ix_job_requirements_source_hash", "job_requirements", ["source_hash"])
    op.create_table(
        "qualification_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(64), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "profile_version_id",
            sa.String(36),
            sa.ForeignKey("profile_versions.id"),
            nullable=False,
        ),
        sa.Column("preference_version_id", sa.String(36), sa.ForeignKey("preference_versions.id")),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("requirement_source_hash", sa.String(64), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("eligibility", sa.JSON(), nullable=False),
        sa.Column("missing_requirements", sa.JSON(), nullable=False),
        sa.Column("unverified_claims", sa.JSON(), nullable=False),
        sa.Column("contradictions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "job_id", "profile_version_id", "engine_version"),
    )
    op.create_index(
        "ix_qualification_assessments_candidate_id", "qualification_assessments", ["candidate_id"]
    )
    op.create_index("ix_qualification_assessments_job_id", "qualification_assessments", ["job_id"])
    op.create_table(
        "requirement_evidence_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("qualification_assessments.id"),
            nullable=False,
        ),
        sa.Column(
            "requirement_id", sa.String(36), sa.ForeignKey("job_requirements.id"), nullable=False
        ),
        sa.Column("evidence_id", sa.String(255), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("related_skill", sa.String(255)),
        sa.Column("relevant_dates", sa.JSON(), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("retrieval_confidence", sa.Float(), nullable=False),
        sa.UniqueConstraint("assessment_id", "requirement_id", "evidence_id"),
    )
    op.create_index(
        "ix_requirement_evidence_matches_assessment_id",
        "requirement_evidence_matches",
        ["assessment_id"],
    )
    op.create_index(
        "ix_requirement_evidence_matches_requirement_id",
        "requirement_evidence_matches",
        ["requirement_id"],
    )
    op.create_table(
        "growth_assessments",
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("qualification_assessments.id"),
            primary_key=True,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("band", sa.String(20), nullable=False),
        sa.Column("foundations", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("reasoning", sa.JSON(), nullable=False),
    )
    op.create_table(
        "recommendations",
        sa.Column(
            "assessment_id",
            sa.String(36),
            sa.ForeignKey("qualification_assessments.id"),
            primary_key=True,
        ),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("critic_flags", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recommendations_outcome", "recommendations", ["outcome"])
    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("benchmark_version", sa.String(32), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_benchmark_results_benchmark_version", "benchmark_results", ["benchmark_version"]
    )


def downgrade() -> None:
    for table in (
        "benchmark_results",
        "recommendations",
        "growth_assessments",
        "requirement_evidence_matches",
        "qualification_assessments",
        "job_requirements",
        "claim_reconciliations",
        "repository_analyses",
        "github_contributions",
        "github_repositories",
        "github_profiles",
    ):
        op.drop_table(table)
