from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brokej_search.core.exceptions import NotFoundError
from brokej_search.database.models import (
    Candidate,
    Education,
    Experience,
    GitHubProfile,
    GitHubRepository,
    GrowthAssessment,
    Job,
    JobRequirement,
    PreferenceItem,
    ProfileEntity,
    ProfileSkill,
    QualificationAssessment,
    Recommendation,
    RepositoryAnalysis,
    RequirementEvidenceMatch,
    SkillCatalog,
    new_id,
    utcnow,
)
from brokej_search.evaluation.requirements import RequirementDecomposer
from brokej_search.evaluation.schemas import (
    CandidateEvidence,
    EligibilityAssessment,
    EvaluationResult,
    JobRequirementData,
    RequirementAssessment,
    RequirementSource,
    ScoreDetail,
)

ENGINE_VERSION = "evaluation-v1"
_TECHNICAL = {
    "technical_skill",
    "programming_language",
    "framework_tool",
    "system_design_architecture",
}
_STRENGTH = {
    "direct": 1.0,
    "partial": 0.65,
    "transferable": 0.45,
    "self_reported": 0.35,
    "unverified": 0.15,
    "unknown": 0.0,
    "contradictory": 0.0,
}
_ADJACENT = {
    "fastapi": {"flask", "rest apis", "python"},
    "kubernetes": {"docker", "linux"},
    "machine learning": {"numpy", "pandas", "scikit-learn", "pytorch", "tensorflow"},
    "ml inference": {"machine learning", "fastapi", "tensorflow lite micro"},
    "model serving": {"fastapi", "docker", "rest apis", "machine learning"},
    "distributed systems": {"docker", "rest apis", "websocket"},
}


class EvaluationService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.decomposer = RequirementDecomposer()

    def decompose_job(self, job_id: str) -> list[JobRequirementData]:
        with self.factory.begin() as session:
            job = session.get(Job, job_id)
            if not job:
                raise NotFoundError("Job not found")
            source = self._requirement_source(job)
            source_hash = self._source_hash(source)
            existing = list(
                session.scalars(
                    select(JobRequirement).where(
                        JobRequirement.job_id == job.id,
                        JobRequirement.source_hash == source_hash,
                    )
                )
            )
            if existing:
                return [self._requirement_schema(row) for row in existing]
            requirements = self.decomposer.decompose(source)
            for requirement in requirements:
                session.add(
                    JobRequirement(
                        job_id=job.id,
                        source_hash=source_hash,
                        requirement_key=requirement.id,
                        original_text=requirement.original_text,
                        normalized_competency=requirement.normalized_competency,
                        category=requirement.category,
                        criticality=requirement.criticality,
                        mandatory_status=requirement.mandatory_status,
                        evidence_expected=requirement.evidence_expected,
                        extraction_confidence=requirement.extraction_confidence,
                        source_reference=requirement.source_reference,
                        extractor_version=self.decomposer.version,
                    )
                )
            return requirements

    def assess(self, candidate_id: str, job_id: str) -> EvaluationResult:
        self.decompose_job(job_id)
        with self.factory.begin() as session:
            candidate = session.get(Candidate, candidate_id)
            job = session.get(Job, job_id)
            if not candidate or not candidate.current_profile_version_id:
                raise NotFoundError("Candidate profile not found")
            if not job:
                raise NotFoundError("Job not found")
            source_hash = self._source_hash(self._requirement_source(job))
            preference_hash = hashlib.sha256(
                (candidate.current_preference_version_id or "").encode()
            ).hexdigest()[:8]
            engine_version = f"eval-v1-{source_hash[:8]}-{preference_hash}"
            existing = session.scalar(
                select(QualificationAssessment).where(
                    QualificationAssessment.candidate_id == candidate_id,
                    QualificationAssessment.job_id == job_id,
                    QualificationAssessment.profile_version_id
                    == candidate.current_profile_version_id,
                    QualificationAssessment.engine_version == engine_version,
                )
            )
            if existing:
                return EvaluationResult.model_validate(existing.result)
            requirement_rows = list(
                session.scalars(
                    select(JobRequirement).where(
                        JobRequirement.job_id == job_id,
                        JobRequirement.source_hash == source_hash,
                    )
                )
            )
            requirement_results = [
                self._assess_requirement(session, candidate, row) for row in requirement_rows
            ]
            eligibility = self._eligibility(session, candidate, requirement_results)
            scores = self._scores(session, candidate, job, requirement_results, eligibility)
            growth_score, growth_reasons = self._growth(requirement_results)
            outcome = self._recommend(scores, eligibility, requirement_results, growth_score)
            critic_flags = self._critic(outcome, eligibility, requirement_results)
            if critic_flags and outcome == "priority_shortlist":
                outcome = "manual_review"
            evidence = self._unique_evidence(requirement_results)
            confidence_values = [item.retrieval_confidence for item in evidence]
            confidence = (
                sum(confidence_values) / len(confidence_values) if confidence_values else 0.35
            )
            confidence = max(0.1, min(confidence, 0.7 if critic_flags else 0.95))
            missing = [
                item.requirement
                for item in requirement_results
                if item.status in {"missing", "unknown", "failed"}
            ]
            unverified = [
                item
                for item in evidence
                if item.classification in {"self_reported", "unverified", "unknown"}
            ]
            contradictions = [item for item in evidence if item.classification == "contradictory"]
            assessment_id = new_id()
            now = utcnow()
            result = EvaluationResult(
                assessment_id=assessment_id,
                candidate_id=candidate_id,
                job_id=job_id,
                outcome=outcome,
                scores=scores,
                eligibility=eligibility,
                requirements=requirement_results,
                growth_score=growth_score,
                growth_band="high"
                if growth_score >= 0.7
                else "moderate"
                if growth_score >= 0.4
                else "low",
                supporting_evidence=evidence,
                missing_requirements=missing,
                unverified_claims=unverified,
                contradictory_evidence=contradictions,
                critic_flags=critic_flags,
                confidence=confidence,
                explanation=self._explanation(outcome, eligibility, scores, missing),
                assessed_at=now,
            )
            row = QualificationAssessment(
                id=assessment_id,
                candidate_id=candidate_id,
                job_id=job_id,
                profile_version_id=candidate.current_profile_version_id,
                preference_version_id=candidate.current_preference_version_id,
                engine_version=engine_version,
                requirement_source_hash=source_hash,
                scores={key: value.model_dump(mode="json") for key, value in scores.items()},
                eligibility=eligibility.model_dump(mode="json"),
                missing_requirements=[item.model_dump(mode="json") for item in missing],
                unverified_claims=[item.model_dump(mode="json") for item in unverified],
                contradictions=[item.model_dump(mode="json") for item in contradictions],
                result=result.model_dump(mode="json"),
                confidence=confidence,
                assessed_at=now,
            )
            session.add(row)
            session.flush()
            for requirement_row, requirement_result in zip(
                requirement_rows, requirement_results, strict=True
            ):
                for item in requirement_result.evidence:
                    session.add(
                        RequirementEvidenceMatch(
                            assessment_id=row.id,
                            requirement_id=requirement_row.id,
                            evidence_id=item.evidence_id,
                            source=item.source,
                            description=item.supporting_description,
                            related_skill=item.related_skill,
                            relevant_dates=item.relevant_dates,
                            classification=item.classification,
                            verification_status=item.verification_status,
                            retrieval_confidence=item.retrieval_confidence,
                        )
                    )
            session.add(
                GrowthAssessment(
                    assessment_id=row.id,
                    score=growth_score,
                    band=result.growth_band,
                    foundations=[
                        item.model_dump(mode="json")
                        for item in evidence
                        if item.classification in {"partial", "transferable"}
                    ],
                    gaps=[item.model_dump(mode="json") for item in missing],
                    reasoning=growth_reasons,
                )
            )
            session.add(
                Recommendation(
                    assessment_id=row.id,
                    outcome=outcome,
                    explanation=result.explanation,
                    critic_flags=critic_flags,
                    confidence=confidence,
                )
            )
            return result

    def _assess_requirement(
        self, session: Session, candidate: Candidate, requirement: JobRequirement
    ) -> RequirementAssessment:
        schema = self._requirement_schema(requirement)
        if requirement.criticality == "hard_eligibility":
            return self._assess_hard_eligibility(session, candidate, schema)
        evidence = self._profile_evidence(session, candidate, schema)
        evidence.extend(self._github_evidence(session, candidate, schema))
        best = max((_STRENGTH[item.classification] for item in evidence), default=0)
        if best >= 0.8:
            status, reasoning = (
                "satisfied",
                "Direct implementation or work evidence supports this requirement.",
            )
        elif best >= 0.4:
            status, reasoning = (
                "partial",
                "Related evidence exists but does not establish full current proficiency.",
            )
        elif evidence:
            status, reasoning = "unknown", "Only self-reported or unverified evidence is available."
        elif requirement.criticality == "preferred":
            status, reasoning = (
                "missing",
                "No supporting evidence found for this preferred requirement.",
            )
        else:
            status, reasoning = "missing", "No supporting evidence found."
        return RequirementAssessment(
            requirement=schema, status=status, evidence=evidence, reasoning=reasoning
        )

    def _profile_evidence(
        self, session: Session, candidate: Candidate, requirement: JobRequirementData
    ) -> list[CandidateEvidence]:
        if not requirement.normalized_competency:
            return []
        wanted = requirement.normalized_competency.casefold()
        skills = list(
            session.scalars(
                select(ProfileSkill)
                .join(SkillCatalog)
                .where(ProfileSkill.profile_version_id == candidate.current_profile_version_id)
            )
        )
        output: list[CandidateEvidence] = []
        for skill in skills:
            name = skill.catalog.canonical_name
            folded = name.casefold()
            exact = folded == wanted
            adjacent = folded in _ADJACENT.get(wanted, set())
            if not exact and not adjacent:
                continue
            if skill.evidence:
                for edge in skill.evidence:
                    classification = edge.classification
                    if classification == "candidate_confirmed":
                        classification = "self_reported"
                    if adjacent and classification not in {"unverified", "unknown"}:
                        classification = "transferable"
                    output.append(
                        CandidateEvidence(
                            evidence_id=edge.id,
                            source=f"profile:{edge.entity.entity_type}",
                            supporting_description=edge.explanation,
                            related_skill=name,
                            relevant_dates=self._entity_dates(session, edge.entity_id),
                            classification=classification,
                            verification_status=edge.verification_status,
                            retrieval_confidence=edge.confidence or (0.9 if exact else 0.65),
                        )
                    )
            else:
                output.append(
                    CandidateEvidence(
                        evidence_id=skill.id,
                        source="profile:skill",
                        supporting_description=f"{name} is listed without implementation evidence.",
                        related_skill=name,
                        classification="self_reported"
                        if skill.verification_status == "candidate_confirmed"
                        else "unverified",
                        verification_status=skill.verification_status,
                        retrieval_confidence=0.35,
                    )
                )
        return output

    def _github_evidence(
        self, session: Session, candidate: Candidate, requirement: JobRequirementData
    ) -> list[CandidateEvidence]:
        if not requirement.normalized_competency:
            return []
        profile = session.scalar(
            select(GitHubProfile).where(GitHubProfile.candidate_id == candidate.id)
        )
        if not profile or not profile.enabled or not profile.analysis_authorized:
            return []
        wanted = requirement.normalized_competency.casefold()
        output: list[CandidateEvidence] = []
        repositories = list(
            session.scalars(
                select(GitHubRepository).where(GitHubRepository.github_profile_id == profile.id)
            )
        )
        for repository in repositories:
            analysis = session.scalar(
                select(RepositoryAnalysis)
                .where(RepositoryAnalysis.repository_id == repository.id)
                .order_by(RepositoryAnalysis.analyzed_at.desc())
            )
            if not analysis:
                continue
            languages = {name.casefold() for name in repository.languages}
            signal = (
                wanted in languages
                or (wanted == "fastapi" and analysis.signals.get("fastapi_implementation"))
                or (
                    wanted in {"machine learning", "ml inference"}
                    and analysis.signals.get("ml_pipeline_implementation")
                )
            )
            if not signal:
                continue
            verified_owner = profile.ownership_status == "candidate_confirmed"
            strong = analysis.classification == "substantial_implementation" and not repository.fork
            classification = "direct" if verified_owner and strong else "unverified"
            output.append(
                CandidateEvidence(
                    evidence_id=analysis.id,
                    source="github_repository",
                    supporting_description=(
                        f"{repository.full_name}: {analysis.classification}; "
                        "selected source signals verified."
                    ),
                    related_skill=requirement.normalized_competency,
                    relevant_dates={
                        "repository_updated_at": repository.repository_updated_at.isoformat()
                        if repository.repository_updated_at
                        else None
                    },
                    classification=classification,
                    verification_status="source_verified"
                    if verified_owner
                    else "unverified_ownership",
                    retrieval_confidence=analysis.confidence
                    if verified_owner
                    else min(analysis.confidence, 0.45),
                )
            )
        return output

    def _assess_hard_eligibility(
        self, session: Session, candidate: Candidate, requirement: JobRequirementData
    ) -> RequirementAssessment:
        text = requirement.original_text.casefold()
        if requirement.category == "graduation_eligibility":
            allowed = {int(value) for value in re.findall(r"\b20\d{2}\b", text)}
            years = set(
                session.scalars(
                    select(func.extract("year", Education.end_date))
                    .join(ProfileEntity, ProfileEntity.id == Education.entity_id)
                    .where(ProfileEntity.profile_version_id == candidate.current_profile_version_id)
                )
            )
            years = {int(year) for year in years if year is not None}
            if allowed and years:
                passed = bool(allowed & years)
                evidence = CandidateEvidence(
                    evidence_id=f"education-years:{','.join(map(str, sorted(years)))}",
                    source="profile:education",
                    supporting_description=(
                        f"Recorded graduation year: {', '.join(map(str, sorted(years)))}."
                    ),
                    classification="direct" if passed else "contradictory",
                    verification_status="resume_extracted",
                    retrieval_confidence=0.95,
                )
                return RequirementAssessment(
                    requirement=requirement,
                    status="satisfied" if passed else "failed",
                    evidence=[evidence],
                    reasoning="Graduation year matches the stated range."
                    if passed
                    else "Recorded graduation year is outside the stated eligible years.",
                )
        if requirement.category == "education":
            educations = list(
                session.scalars(
                    select(Education)
                    .join(ProfileEntity, ProfileEntity.id == Education.entity_id)
                    .where(ProfileEntity.profile_version_id == candidate.current_profile_version_id)
                )
            )
            if educations:
                degrees = " ".join(
                    f"{row.degree or ''} {row.discipline or ''}" for row in educations
                ).casefold()
                degree_terms = {
                    term
                    for term in ("bachelor", "master", "phd", "computer science", "engineering")
                    if term in text
                }
                if degree_terms:
                    passed = any(term in degrees for term in degree_terms)
                    evidence = CandidateEvidence(
                        evidence_id=educations[0].entity_id,
                        source="profile:education",
                        supporting_description=degrees.strip(),
                        classification="direct" if passed else "contradictory",
                        verification_status="resume_extracted",
                        retrieval_confidence=0.85,
                    )
                    return RequirementAssessment(
                        requirement=requirement,
                        status="satisfied" if passed else "failed",
                        evidence=[evidence],
                        reasoning=(
                            "Education record was compared with the explicit degree restriction."
                        ),
                    )
        if requirement.category == "experience":
            needed_match = re.search(r"\b(\d+)\+?\s*(?:years?|yrs?)\b", text)
            if needed_match:
                needed = int(needed_match.group(1))
                rows = list(
                    session.scalars(
                        select(Experience)
                        .join(ProfileEntity, ProfileEntity.id == Experience.entity_id)
                        .where(
                            ProfileEntity.profile_version_id == candidate.current_profile_version_id
                        )
                    )
                )
                months = sum(
                    max(0, ((row.end_date or datetime.now(UTC).date()) - row.start_date).days // 30)
                    for row in rows
                    if row.start_date
                )
                if rows:
                    passed = months >= needed * 12
                    evidence = CandidateEvidence(
                        evidence_id="experience-duration",
                        source="profile:experience",
                        supporting_description=(
                            f"Approximately {months} months of dated experience are recorded."
                        ),
                        classification="direct" if passed else "contradictory",
                        verification_status="resume_extracted",
                        retrieval_confidence=0.8,
                    )
                    return RequirementAssessment(
                        requirement=requirement,
                        status="satisfied" if passed else "failed",
                        evidence=[evidence],
                        reasoning="Dated experience was compared with the explicit minimum.",
                    )
        preferences = self._preferences(session, candidate)
        key = "authorization" if requirement.category == "work_authorization" else "location"
        matching = [item for item in preferences if key in item.preference_type]
        if matching and any(item.value for item in matching):
            # Candidate-confirmed exclusions are failures; other values remain explicit evidence.
            failed = any(item.state in {"avoid", "exclude"} for item in matching)
            evidence = CandidateEvidence(
                evidence_id=matching[0].id,
                source="candidate_preference",
                supporting_description=matching[0].value or "unknown",
                classification="contradictory" if failed else "self_reported",
                verification_status="candidate_confirmed",
                retrieval_confidence=0.9,
            )
            return RequirementAssessment(
                requirement=requirement,
                status="failed" if failed else "satisfied",
                evidence=[evidence],
                reasoning="Candidate-confirmed preference or eligibility data was used.",
            )
        return RequirementAssessment(
            requirement=requirement,
            status="unknown",
            evidence=[],
            reasoning="Eligibility cannot be established from available candidate data.",
        )

    @staticmethod
    def _eligibility(
        session: Session,
        candidate: Candidate,
        results: list[RequirementAssessment],
    ) -> EligibilityAssessment:
        requirements = [
            item for item in results if item.requirement.criticality == "hard_eligibility"
        ]
        if not requirements:
            return EligibilityAssessment(
                status="not_applicable",
                requirements=[],
                reasoning=["No explicit hard eligibility condition was extracted."],
            )
        if any(item.status == "failed" for item in requirements):
            return EligibilityAssessment(
                status="failed",
                requirements=requirements,
                reasoning=["At least one confirmed hard eligibility condition is not met."],
            )
        if any(item.status == "unknown" for item in requirements):
            return EligibilityAssessment(
                status="unknown",
                requirements=requirements,
                reasoning=["At least one hard eligibility condition is unresolved."],
            )
        return EligibilityAssessment(
            status="passed",
            requirements=requirements,
            reasoning=["All extracted hard eligibility conditions are supported."],
        )

    def _scores(
        self,
        session: Session,
        candidate: Candidate,
        job: Job,
        results: list[RequirementAssessment],
        eligibility: EligibilityAssessment,
    ) -> dict[str, ScoreDetail]:
        technical = [item for item in results if item.requirement.category in _TECHNICAL]
        responsibilities = [
            item for item in results if item.requirement.category == "responsibility"
        ]
        evidence = self._unique_evidence(results)
        technical_value = self._mean_strength(technical)
        responsibility_value = self._mean_strength(responsibilities)
        experience_evidence = [
            item
            for item in evidence
            if item.source in {"profile:experience", "profile:project", "github_repository"}
        ]
        experience_value = (
            sum(_STRENGTH[item.classification] for item in experience_evidence)
            / len(experience_evidence)
            if experience_evidence
            else None
        )
        confidence_value = (
            sum(item.retrieval_confidence for item in evidence) / len(evidence) if evidence else 0.0
        )
        preference_items = self._preferences(session, candidate)
        target_values = [
            item.value.casefold()
            for item in preference_items
            if item.value and item.state in {"target", "prefer"}
        ]
        job_text = f"{job.title} {job.description_text}".casefold()
        interest_value = 1.0 if any(value in job_text for value in target_values) else None
        freshness = 0.5
        if job.posting_date:
            age = utcnow() - job.posting_date.replace(tzinfo=job.posting_date.tzinfo or UTC)
            freshness = (
                1.0 if age <= timedelta(days=14) else 0.7 if age <= timedelta(days=45) else 0.3
            )
        return {
            "technical_qualification": self._score(
                technical_value,
                "Technical requirements are scored from requirement-level evidence.",
            ),
            "project_experience_relevance": self._score(
                experience_value,
                "Only implementation, contribution, project, and dated experience "
                "evidence is counted.",
            ),
            "responsibility_alignment": self._score(
                responsibility_value,
                "Responsibilities are assessed separately from skill mentions.",
            ),
            "eligibility": ScoreDetail(
                value=1.0
                if eligibility.status in {"passed", "not_applicable"}
                else 0.0
                if eligibility.status == "failed"
                else None,
                status="failed"
                if eligibility.status == "failed"
                else "unknown"
                if eligibility.status == "unknown"
                else "measured",
                reasoning="Hard eligibility is a gate, not a compensating weighted score.",
            ),
            "career_interest_alignment": self._score(
                interest_value,
                "Candidate preference targets are matched conservatively; absent preferences "
                "remain unknown.",
            ),
            "opportunity_quality_freshness": self._score(
                freshness, "Freshness uses only the source posting timestamp."
            ),
            "evidence_confidence": self._score(
                confidence_value,
                "Confidence reflects provenance and retrieval quality, not candidate ability.",
            ),
        }

    @staticmethod
    def _score(value: float | None, reasoning: str) -> ScoreDetail:
        return ScoreDetail(
            value=value, status="measured" if value is not None else "unknown", reasoning=reasoning
        )

    @staticmethod
    def _mean_strength(results: list[RequirementAssessment]) -> float | None:
        if not results:
            return None
        weighted: list[tuple[float, float]] = []
        for result in results:
            weight = (
                0.25
                if result.requirement.criticality == "preferred"
                else 0.5
                if result.requirement.criticality in {"trainable", "unknown"}
                else 1.0
            )
            strength = max(
                (_STRENGTH[item.classification] for item in result.evidence), default=0.0
            )
            weighted.append((strength, weight))
        return sum(value * weight for value, weight in weighted) / sum(
            weight for _, weight in weighted
        )

    @staticmethod
    def _growth(results: list[RequirementAssessment]) -> tuple[float, list[str]]:
        gaps = [
            item
            for item in results
            if item.requirement.category in _TECHNICAL and item.status != "satisfied"
        ]
        if not gaps:
            return 0.8, [
                "No material technical gap was found; growth reflects continued role learning, "
                "not missing proficiency."
            ]
        values = []
        for gap in gaps:
            classifications = {item.classification for item in gap.evidence}
            if "partial" in classifications:
                values.append(0.7)
            elif "transferable" in classifications:
                values.append(0.6)
            elif gap.requirement.criticality == "trainable":
                values.append(0.65)
            else:
                values.append(0.2)
        score = sum(values) / len(values)
        return score, [
            "Growth is based on explicit adjacent foundations and trainability; it is not "
            "counted as current proficiency."
        ]

    @staticmethod
    def _recommend(
        scores: dict[str, ScoreDetail],
        eligibility: EligibilityAssessment,
        results: list[RequirementAssessment],
        growth: float,
    ) -> str:
        if eligibility.status == "failed":
            return "ineligible"
        if eligibility.status == "unknown":
            return "manual_review"
        if not results:
            return "manual_review"
        core = [item for item in results if item.requirement.criticality == "core_mandatory"]
        core_missing = [item for item in core if item.status in {"missing", "unknown", "failed"}]
        technical = scores["technical_qualification"].value
        if core and all(item.status == "satisfied" for item in core):
            return "priority_shortlist"
        if len(core_missing) <= 1 and growth >= 0.55:
            return "growth_opportunity"
        if core_missing and growth < 0.4:
            return "do_not_prioritize"
        if len(core_missing) >= 2 or technical is not None and technical < 0.35:
            return "do_not_prioritize"
        return "manual_review"

    @staticmethod
    def _critic(
        outcome: str,
        eligibility: EligibilityAssessment,
        results: list[RequirementAssessment],
    ) -> list[str]:
        flags: list[str] = []
        if eligibility.status == "unknown":
            flags.append("Unresolved hard eligibility requires manual review.")
        if any(item.requirement.criticality == "mandatory_but_ambiguous" for item in results):
            flags.append("At least one mandatory statement is ambiguous.")
        if outcome == "priority_shortlist" and any(
            item.requirement.criticality == "core_mandatory" and item.status != "satisfied"
            for item in results
        ):
            flags.append("Priority recommendation had an unsupported core requirement.")
        if any(
            item.classification == "unverified" and item.source == "github_repository"
            for result in results
            for item in result.evidence
        ):
            flags.append("GitHub ownership or implementation attribution is unverified.")
        return flags

    @staticmethod
    def _explanation(
        outcome: str,
        eligibility: EligibilityAssessment,
        scores: dict[str, ScoreDetail],
        missing: list[JobRequirementData],
    ) -> str:
        technical = scores["technical_qualification"].value
        technical_text = "unknown" if technical is None else f"{technical:.2f}"
        return (
            f"Recommendation: {outcome}. Eligibility is {eligibility.status}; technical "
            f"qualification is {technical_text}; {len(missing)} requirement(s) are missing, "
            "failed, or unresolved."
        )

    @staticmethod
    def _unique_evidence(results: list[RequirementAssessment]) -> list[CandidateEvidence]:
        values: dict[str, CandidateEvidence] = {}
        for result in results:
            for item in result.evidence:
                values[item.evidence_id] = item
        return list(values.values())

    @staticmethod
    def _preferences(session: Session, candidate: Candidate) -> list[PreferenceItem]:
        if not candidate.current_preference_version_id:
            return []
        return list(
            session.scalars(
                select(PreferenceItem).where(
                    PreferenceItem.preference_version_id == candidate.current_preference_version_id
                )
            )
        )

    @staticmethod
    def _entity_dates(session: Session, entity_id: str) -> dict[str, str | None]:
        experience = session.get(Experience, entity_id)
        if not experience:
            return {}
        return {
            "start": experience.start_date.isoformat() if experience.start_date else None,
            "end": experience.end_date.isoformat() if experience.end_date else None,
        }

    @staticmethod
    def _requirement_source(job: Job) -> RequirementSource:
        return RequirementSource(
            description=job.description_text,
            required_skills=job.required_skills,
            preferred_skills=job.preferred_skills,
            experience_requirements=job.experience_requirements,
            education_requirements=job.education_requirements,
            graduation_year_restrictions=job.graduation_year_restrictions,
            locations=job.locations,
            work_arrangement=job.work_arrangement,
        )

    @staticmethod
    def _source_hash(source: RequirementSource) -> str:
        return hashlib.sha256(
            json.dumps(source.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _requirement_schema(row: JobRequirement) -> JobRequirementData:
        return JobRequirementData(
            id=row.requirement_key,
            original_text=row.original_text,
            normalized_competency=row.normalized_competency,
            category=row.category,
            criticality=row.criticality,
            mandatory_status=row.mandatory_status,
            evidence_expected=row.evidence_expected,
            extraction_confidence=row.extraction_confidence,
            source_reference=row.source_reference,
        )
