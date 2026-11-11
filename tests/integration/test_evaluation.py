from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from brokej_search.database.models import (
    Candidate,
    Education,
    EntityStatement,
    EvidenceEdge,
    Job,
    PreferenceItem,
    PreferenceVersion,
    ProfileEntity,
    ProfileSkill,
    ProfileVersion,
    QualificationAssessment,
    SkillCatalog,
    SourceDocument,
    SourceFragment,
)


def _seed_candidate(
    runtime, candidate_id: str, skills: list[str], graduation_year: int = 2027
) -> None:
    with runtime.factory.begin() as session:
        candidate = Candidate(id=candidate_id, display_name="Candidate")
        session.add(candidate)
        session.flush()
        document = SourceDocument(
            candidate_id=candidate_id,
            source_type="candidate_input",
            original_name="fixture",
            storage_key="fixture",
            sha256=hashlib.sha256(candidate_id.encode()).hexdigest(),
            mime_type="text/plain",
            byte_size=1,
            page_count=1,
            extractor_name="fixture",
            extractor_version="1",
            extraction_status="succeeded",
            extracted_text="fixture",
        )
        session.add(document)
        session.flush()
        fragment = SourceFragment(
            source_document_id=document.id,
            page_number=1,
            source_text="fixture evidence",
            verification_status="candidate_confirmed",
        )
        session.add(fragment)
        session.flush()
        version = ProfileVersion(
            candidate_id=candidate_id,
            version_number=1,
            source_document_id=document.id,
            semantic_hash=hashlib.sha256(f"profile-{candidate_id}".encode()).hexdigest(),
        )
        session.add(version)
        session.flush()
        education = ProfileEntity(
            profile_version_id=version.id,
            entity_type="education",
            identity_key="education",
            verification_status="candidate_confirmed",
            source_fragment_id=fragment.id,
        )
        session.add(education)
        session.flush()
        session.add(
            Education(
                entity_id=education.id,
                institution="University",
                degree="Bachelor of Engineering",
                discipline="Engineering",
                end_date=date(graduation_year, 5, 1),
                expected_graduation=True,
            )
        )
        project = ProfileEntity(
            profile_version_id=version.id,
            entity_type="project",
            identity_key="project",
            verification_status="candidate_confirmed",
            source_fragment_id=fragment.id,
        )
        session.add(project)
        session.flush()
        statement = EntityStatement(
            entity_id=project.id,
            statement_type="technical_change",
            text="Implemented and tested the project.",
            source_fragment_id=fragment.id,
            verification_status="candidate_confirmed",
        )
        session.add(statement)
        session.flush()
        for skill_name in skills:
            catalog = session.scalar(
                select(SkillCatalog).where(SkillCatalog.canonical_name == skill_name)
            )
            if not catalog:
                catalog = SkillCatalog(canonical_name=skill_name, category="test")
                session.add(catalog)
                session.flush()
            skill = ProfileSkill(
                profile_version_id=version.id,
                skill_id=catalog.id,
                verification_status="candidate_confirmed",
            )
            session.add(skill)
            session.flush()
            session.add(
                EvidenceEdge(
                    profile_skill_id=skill.id,
                    entity_id=project.id,
                    statement_id=statement.id,
                    source_fragment_id=fragment.id,
                    classification="direct",
                    explanation=f"Implemented {skill_name} in a project.",
                    verification_status="candidate_confirmed",
                    confidence=0.9,
                )
            )
        candidate.current_profile_version_id = version.id


def _seed_job(
    runtime,
    job_id: str,
    *,
    required: list[str],
    preferred: list[str] | None = None,
    graduation: str | None = None,
    education: str | None = None,
    experience: str | None = None,
    description: str = "",
) -> None:
    with runtime.factory.begin() as session:
        session.add(
            Job(
                id=job_id,
                title="Backend Engineer",
                normalized_title="backend engineer",
                company_name="Example",
                normalized_company="example",
                description_text=description,
                listing_url=f"https://jobs.example/{job_id}",
                required_skills=required,
                preferred_skills=preferred or [],
                graduation_year_restrictions=graduation,
                education_requirements=education,
                experience_requirements=experience,
                status="active",
            )
        )


def test_profile_to_evidence_to_reproducible_recommendation(runtime) -> None:
    _seed_candidate(runtime, "candidate-fit", ["Python", "FastAPI"])
    _seed_job(runtime, "job-fit", required=["Python", "FastAPI"], preferred=["Kubernetes"])
    first = runtime.evaluation.assess("candidate-fit", "job-fit")
    second = runtime.evaluation.assess("candidate-fit", "job-fit")
    assert first.outcome == "priority_shortlist"
    assert first.assessment_id == second.assessment_id
    assert {item.related_skill for item in first.supporting_evidence} >= {"Python", "FastAPI"}
    with runtime.factory() as session:
        assert session.scalar(select(func.count(QualificationAssessment.id))) == 1


def test_preference_version_change_produces_a_fresh_assessment(runtime) -> None:
    _seed_candidate(runtime, "candidate-pref", ["Python"])
    _seed_job(runtime, "job-pref", required=["Python"])
    first = runtime.evaluation.assess("candidate-pref", "job-pref")
    with runtime.factory.begin() as session:
        candidate = session.get(Candidate, "candidate-pref")
        preference = PreferenceVersion(
            candidate_id="candidate-pref",
            version_number=1,
            semantic_hash=hashlib.sha256(b"preference").hexdigest(),
            source="candidate",
        )
        session.add(preference)
        session.flush()
        session.add(
            PreferenceItem(
                preference_version_id=preference.id,
                preference_type="role_family",
                value="Backend Engineer",
                state="target",
            )
        )
        candidate.current_preference_version_id = preference.id
    second = runtime.evaluation.assess("candidate-pref", "job-pref")
    assert second.assessment_id != first.assessment_id
    assert second.scores["career_interest_alignment"].value == 1.0


def test_hard_graduation_failure_is_ineligible(runtime) -> None:
    _seed_candidate(runtime, "candidate-grad", ["Python"], graduation_year=2027)
    _seed_job(
        runtime,
        "job-grad",
        required=["Python"],
        graduation="Only candidates graduating in 2025 or 2026",
    )
    result = runtime.evaluation.assess("candidate-grad", "job-grad")
    assert result.eligibility.status == "failed"
    assert result.outcome == "ineligible"
    assert result.contradictory_evidence


def test_transferable_ml_foundation_is_growth_not_current_proficiency(runtime) -> None:
    _seed_candidate(runtime, "candidate-growth", ["Python", "scikit-learn"])
    _seed_job(runtime, "job-growth", required=["Python", "Machine Learning"])
    result = runtime.evaluation.assess("candidate-growth", "job-growth")
    ml = next(
        item
        for item in result.requirements
        if item.requirement.normalized_competency == "Machine Learning"
    )
    assert ml.status == "partial"
    assert all(item.classification == "transferable" for item in ml.evidence)
    assert result.outcome == "growth_opportunity"


def test_backend_only_candidate_is_not_qualified_for_mandatory_ml(runtime) -> None:
    _seed_candidate(runtime, "candidate-backend", ["Python", "FastAPI"])
    _seed_job(runtime, "job-ml", required=["Python", "FastAPI", "Machine Learning"])
    result = runtime.evaluation.assess("candidate-backend", "job-ml")
    assert result.outcome == "do_not_prioritize"
    assert any(
        item.normalized_competency == "Machine Learning" for item in result.missing_requirements
    )


def test_ambiguous_mandatory_description_triggers_critic(runtime) -> None:
    _seed_candidate(runtime, "candidate-ambiguous", ["Python"])
    _seed_job(
        runtime,
        "job-ambiguous",
        required=["Python"],
        description="You must build reliable developer tools.",
    )
    result = runtime.evaluation.assess("candidate-ambiguous", "job-ambiguous")
    assert result.outcome == "manual_review"
    assert "ambiguous" in " ".join(result.critic_flags).casefold()


def test_curated_benchmark_recommendations(runtime, fixture_dir: Path) -> None:
    cases = json.loads((fixture_dir / "evaluation_benchmark.json").read_text())
    actual: list[str] = []
    expected: list[str] = []
    for index, case in enumerate(cases):
        candidate_id = f"benchmark-candidate-{index}"
        job_id = f"benchmark-job-{index}"
        _seed_candidate(
            runtime,
            candidate_id,
            case["candidate"]["skills"],
            graduation_year=case["candidate"]["graduation_year"],
        )
        job = case.get("job", {})
        _seed_job(
            runtime,
            job_id,
            required=job.get("required", []),
            preferred=job.get("preferred"),
            graduation=job.get("graduation"),
            education=job.get("education"),
            experience=job.get("experience"),
            description=job.get("description", ""),
        )
        actual.append(runtime.evaluation.assess(candidate_id, job_id).outcome)
        expected.append(case["expected"]["recommendation"])
    assert actual == expected
