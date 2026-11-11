from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from brokej_search.career_profile.extraction import PdfDocumentExtractor
from brokej_search.career_profile.normalization import normalize_skill
from brokej_search.career_profile.parser import DeterministicResumeParser
from brokej_search.career_profile.schemas import (
    CompletenessReport,
    IngestionResult,
    ParsedEntity,
    ParsedProfile,
    ValidationItem,
)
from brokej_search.core.config import Settings
from brokej_search.core.exceptions import NotFoundError
from brokej_search.database.models import (
    Achievement,
    Candidate,
    CandidateDetail,
    Contribution,
    Education,
    EntityStatement,
    EvidenceEdge,
    Experience,
    IngestionRun,
    PreferenceItem,
    PreferenceVersion,
    ProfileEntity,
    ProfileSkill,
    ProfileVersion,
    Project,
    SkillCatalog,
    SourceDocument,
    SourceFragment,
    ValidationReport,
    utcnow,
)

TARGET_ROLES = [
    "ML Infrastructure Engineering",
    "Inference Engineering",
    "DevOps / Platform Engineering",
    "Backend / Software Engineering",
    "AI Systems Engineering",
    "Embedded ML / Edge AI",
    "ML Research Internships",
]
UNKNOWN_PREFERENCES = [
    "opportunity_type",
    "work_arrangement",
    "location",
    "compensation",
    "work_authorization",
    "experience_requirement",
    "application_deadline",
]


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _canonical_profile(profile: ParsedProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json", exclude={"issues"})


def _semantic_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class ProfileService:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.extractor = PdfDocumentExtractor()
        self.parser = DeterministicResumeParser()

    def ingest_resume(self, candidate_id: str, path: Path) -> IngestionResult:
        extracted = self.extractor.extract(path)
        parsed = self.parser.parse(extracted)
        unique_entities: list[ParsedEntity] = []
        seen_entities: set[tuple[str, str]] = set()
        for entity in parsed.entities:
            identity = (entity.entity_type, entity.identity_key)
            if identity in seen_entities:
                parsed.issues.append(
                    {
                        "code": "duplicate_entity",
                        "severity": "warning",
                        "entity": entity.identity_key,
                    }
                )
                continue
            seen_entities.add(identity)
            unique_entities.append(entity)
        parsed.entities = unique_entities
        semantic_hash = _semantic_hash(_canonical_profile(parsed))
        storage_key = f"{extracted.sha256}.pdf"
        storage_path = self.settings.source_storage / storage_key
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not storage_path.exists():
            temporary = storage_path.with_suffix(".tmp")
            shutil.copyfile(path, temporary)
            os.chmod(temporary, 0o600)
            temporary.replace(storage_path)

        with self.factory() as session, session.begin():
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                candidate = Candidate(id=candidate_id, display_name=parsed.name)
                session.add(candidate)
                session.flush()

            document = session.scalar(
                select(SourceDocument).where(
                    SourceDocument.candidate_id == candidate_id,
                    SourceDocument.sha256 == extracted.sha256,
                    SourceDocument.source_type == "resume_pdf",
                )
            )
            if document is None:
                document = SourceDocument(
                    candidate_id=candidate_id,
                    source_type="resume_pdf",
                    original_name=path.name,
                    storage_key=storage_key,
                    sha256=extracted.sha256,
                    mime_type="application/pdf",
                    byte_size=extracted.byte_size,
                    page_count=extracted.page_count,
                    extractor_name=self.extractor.name,
                    extractor_version=self.extractor.version,
                    extraction_status="partial" if extracted.warnings else "succeeded",
                    extracted_text=extracted.text,
                )
                session.add(document)
                session.flush()
                fragments = self._create_fragments(session, document, parsed)
            else:
                fragments = {
                    row.section_name or "": row
                    for row in session.scalars(
                        select(SourceFragment).where(
                            SourceFragment.source_document_id == document.id
                        )
                    )
                }

            current = (
                session.get(ProfileVersion, candidate.current_profile_version_id)
                if candidate.current_profile_version_id
                else None
            )
            identical = session.scalar(
                select(ProfileVersion).where(
                    ProfileVersion.candidate_id == candidate_id,
                    ProfileVersion.semantic_hash == semantic_hash,
                )
            )
            if identical:
                candidate.current_profile_version_id = identical.id
                run = IngestionRun(
                    candidate_id=candidate_id,
                    source_document_id=document.id,
                    parser_name=self.parser.name,
                    parser_version=self.parser.version,
                    status="succeeded",
                    profile_version_id=identical.id,
                    semantic_noop=True,
                    issues=parsed.issues,
                    completed_at=utcnow(),
                )
                session.add(run)
                report = self._validate(session, candidate, identical)
                return self._result(session, candidate, identical, True, report)

            version_number = (current.version_number + 1) if current else 1
            version = ProfileVersion(
                candidate_id=candidate_id,
                version_number=version_number,
                previous_version_id=current.id if current else None,
                source_document_id=document.id,
                semantic_hash=semantic_hash,
                change_summary={"source": path.name, "parser_issues": len(parsed.issues)},
            )
            session.add(version)
            session.flush()
            version.details = CandidateDetail(
                professional_name=parsed.name,
                professional_summary=parsed.summary,
                email=parsed.email,
                phone=parsed.phone,
                linkedin_url=parsed.linkedin_url,
                github_url=parsed.github_url,
            )
            entity_rows = self._persist_entities(session, version, parsed.entities, fragments)
            self._persist_skills(session, version, parsed, entity_rows, fragments)
            candidate.display_name = parsed.name or candidate.display_name
            candidate.current_profile_version_id = version.id
            if not candidate.current_preference_version_id:
                preference = self._initial_preferences(candidate_id)
                session.add(preference)
                session.flush()
                candidate.current_preference_version_id = preference.id
            run = IngestionRun(
                candidate_id=candidate_id,
                source_document_id=document.id,
                parser_name=self.parser.name,
                parser_version=self.parser.version,
                status="succeeded",
                profile_version_id=version.id,
                semantic_noop=False,
                issues=parsed.issues,
                completed_at=utcnow(),
            )
            session.add(run)
            session.flush()
            report = self._validate(session, candidate, version, parsed.issues)
            return self._result(session, candidate, version, False, report)

    def _create_fragments(
        self, session: Session, document: SourceDocument, parsed: ParsedProfile
    ) -> dict[str, SourceFragment]:
        fragments: dict[str, SourceFragment] = {}
        for section, text in parsed.sections.items():
            fragment = SourceFragment(
                source_document_id=document.id,
                page_number=1,
                section_name=section,
                source_text=text,
                extracted_value=text,
            )
            session.add(fragment)
            fragments[section] = fragment
        session.flush()
        return fragments

    def _persist_entities(
        self,
        session: Session,
        version: ProfileVersion,
        entities: list[ParsedEntity],
        fragments: dict[str, SourceFragment],
    ) -> dict[str, tuple[ProfileEntity, list[EntityStatement], ParsedEntity]]:
        rows: dict[str, tuple[ProfileEntity, list[EntityStatement], ParsedEntity]] = {}
        for order, item in enumerate(entities):
            fragment = fragments.get(item.section)
            entity = ProfileEntity(
                profile_version_id=version.id,
                entity_type=item.entity_type,
                identity_key=item.identity_key,
                display_order=order,
                verification_status=item.verification_status,
                source_fragment_id=fragment.id if fragment else None,
            )
            session.add(entity)
            session.flush()
            if item.entity_type == "experience":
                session.add(
                    Experience(
                        entity_id=entity.id,
                        organization=item.data["organization"],
                        role=item.data["role"],
                        location=item.data.get("location"),
                        work_arrangement=item.data.get("work_arrangement"),
                        start_date=_parse_date(item.data.get("start_date")),
                        end_date=_parse_date(item.data.get("end_date")),
                        employment_type=item.data.get("employment_type"),
                    )
                )
            elif item.entity_type == "project":
                session.add(
                    Project(
                        entity_id=entity.id,
                        name=item.data["name"],
                        short_description=item.data.get("short_description"),
                        problem_addressed=item.data.get("problem_addressed"),
                        repository_url=item.data.get("repository_url"),
                        documentation_url=item.data.get("documentation_url"),
                    )
                )
            elif item.entity_type == "education":
                session.add(
                    Education(
                        entity_id=entity.id,
                        institution=item.data["institution"],
                        degree=item.data.get("degree"),
                        discipline=item.data.get("discipline"),
                        location=item.data.get("location"),
                        start_date=_parse_date(item.data.get("start_date")),
                        end_date=_parse_date(item.data.get("end_date")),
                        expected_graduation=bool(item.data.get("expected_graduation")),
                        academic_details=item.data.get("academic_details"),
                    )
                )
            elif item.entity_type == "contribution":
                session.add(
                    Contribution(
                        entity_id=entity.id,
                        repository=item.data["repository"],
                        reference=item.data.get("reference"),
                        contribution_type=item.data.get("contribution_type"),
                        status=item.data.get("status", "unknown"),
                        evidence_url=item.data.get("evidence_url"),
                    )
                )
            else:
                session.add(
                    Achievement(
                        entity_id=entity.id,
                        name=item.data["name"],
                        organization=item.data.get("organization"),
                        achieved_year=item.data.get("achieved_year"),
                        description=item.data.get("description"),
                    )
                )
            statements: list[EntityStatement] = []
            for index, text in enumerate(item.statements):
                statement = EntityStatement(
                    entity_id=entity.id,
                    statement_type="achievement"
                    if item.entity_type == "experience"
                    else "description",
                    text=text,
                    ordinal=index,
                    source_fragment_id=fragment.id if fragment else None,
                )
                session.add(statement)
                statements.append(statement)
            session.flush()
            rows[item.identity_key] = (entity, statements, item)
        return rows

    def _persist_skills(
        self,
        session: Session,
        version: ProfileVersion,
        parsed: ParsedProfile,
        entity_rows: dict[str, tuple[ProfileEntity, list[EntityStatement], ParsedEntity]],
        fragments: dict[str, SourceFragment],
    ) -> None:
        competency_fragment = fragments.get("CORE COMPETENCIES")
        for parsed_skill in parsed.skills:
            catalog = session.scalar(
                select(SkillCatalog).where(
                    SkillCatalog.canonical_name == parsed_skill.canonical_name
                )
            )
            if catalog is None:
                catalog = SkillCatalog(
                    canonical_name=parsed_skill.canonical_name,
                    category=parsed_skill.category,
                    aliases=[parsed_skill.original]
                    if parsed_skill.original != parsed_skill.canonical_name
                    else [],
                )
                session.add(catalog)
                session.flush()
            skill = ProfileSkill(
                profile_version_id=version.id,
                skill_id=catalog.id,
                verification_status="unverified",
            )
            session.add(skill)
            session.flush()
            for entity, statements, parsed_entity in entity_rows.values():
                canonical_technologies = {
                    normalize_skill(value)[0].casefold() for value in parsed_entity.technologies
                }
                searchable = " ".join(
                    [parsed_entity.title, *[s.text for s in statements]]
                ).casefold()
                if (
                    parsed_skill.canonical_name.casefold() not in canonical_technologies
                    and parsed_skill.canonical_name.casefold() not in searchable
                ):
                    continue
                statement = next(
                    (
                        s
                        for s in statements
                        if parsed_skill.canonical_name.casefold() in s.text.casefold()
                    ),
                    statements[0] if statements else None,
                )
                source_fragment_id = (
                    statement.source_fragment_id
                    if statement and statement.source_fragment_id
                    else entity.source_fragment_id
                    or (competency_fragment.id if competency_fragment else None)
                )
                if not source_fragment_id:
                    continue
                session.add(
                    EvidenceEdge(
                        profile_skill_id=skill.id,
                        entity_id=entity.id,
                        statement_id=statement.id if statement else None,
                        source_fragment_id=source_fragment_id,
                        classification="direct",
                        explanation=(
                            f"{parsed_entity.title} explicitly uses {parsed_skill.canonical_name}."
                        ),
                        verification_status="resume_extracted",
                        confidence=1.0,
                    )
                )
                skill.verification_status = "resume_extracted"

    def _initial_preferences(self, candidate_id: str) -> PreferenceVersion:
        values = [
            {"type": "role_family", "value": role, "state": "target", "priority": index + 1}
            for index, role in enumerate(TARGET_ROLES)
        ]
        values.extend(
            [
                {"type": "excluded_category", "value": "Blockchain / Web3", "state": "avoid"},
                {
                    "type": "dsa_focus",
                    "value": "competitive programming primary",
                    "state": "exclude",
                },
                {"type": "role_family", "value": "compiler / low-level systems", "state": "avoid"},
            ]
        )
        values.extend(
            {"type": kind, "value": None, "state": "unknown"} for kind in UNKNOWN_PREFERENCES
        )
        version = PreferenceVersion(
            candidate_id=candidate_id,
            version_number=1,
            semantic_hash=_semantic_hash(values),
            source="implementation_brief",
        )
        version.items = [
            PreferenceItem(
                preference_type=item["type"],
                value=item.get("value"),
                state=item["state"],
                priority=item.get("priority"),
                is_hard_constraint=True if item["state"] == "exclude" else None,
            )
            for item in values
        ]
        return version

    def update_preferences(self, candidate_id: str, items: list[dict[str, Any]]) -> str:
        canonical = sorted(
            items, key=lambda item: (item["preference_type"], item.get("value") or "")
        )
        digest = _semantic_hash(canonical)
        with self.factory() as session, session.begin():
            candidate = session.get(Candidate, candidate_id)
            if not candidate:
                raise NotFoundError("Candidate not found")
            current = session.get(PreferenceVersion, candidate.current_preference_version_id)
            if current and current.semantic_hash == digest:
                return current.id
            version = PreferenceVersion(
                candidate_id=candidate_id,
                version_number=(current.version_number + 1) if current else 1,
                previous_version_id=current.id if current else None,
                semantic_hash=digest,
                source="candidate",
                items=[PreferenceItem(**item) for item in canonical],
            )
            session.add(version)
            session.flush()
            candidate.current_preference_version_id = version.id
            return version.id

    def _validate(
        self,
        session: Session,
        candidate: Candidate,
        version: ProfileVersion,
        parser_issues: list[dict[str, Any]] | None = None,
    ) -> CompletenessReport:
        items: list[ValidationItem] = []
        entities = list(
            session.scalars(
                select(ProfileEntity).where(ProfileEntity.profile_version_id == version.id)
            )
        )
        skills = list(
            session.scalars(
                select(ProfileSkill).where(ProfileSkill.profile_version_id == version.id)
            )
        )
        for skill in skills:
            count = session.scalar(
                select(func.count(EvidenceEdge.id)).where(EvidenceEdge.profile_skill_id == skill.id)
            )
            if not count:
                items.append(
                    ValidationItem(
                        severity="warning",
                        code="skill_without_evidence",
                        message=(
                            f"{skill.catalog.canonical_name} is listed but has no work evidence."
                        ),
                        entity_id=skill.id,
                        suggested_action=(
                            "Confirm the skill or link it to a project, "
                            "experience, or contribution."
                        ),
                    )
                )
        for entity in entities:
            if (
                entity.entity_type in {"experience", "project", "contribution"}
                and not entity.statements
            ):
                items.append(
                    ValidationItem(
                        severity="warning",
                        code="incomplete_entity_description",
                        message=f"{entity.entity_type} has no supporting statements.",
                        entity_id=entity.id,
                    )
                )
            dated: Experience | Education | None = None
            if entity.entity_type == "experience":
                dated = session.get(Experience, entity.id)
            elif entity.entity_type == "education":
                dated = session.get(Education, entity.id)
            if dated and (not dated.start_date or not dated.end_date):
                items.append(
                    ValidationItem(
                        severity="warning",
                        code="missing_dates",
                        message=f"{entity.entity_type} has incomplete dates.",
                        entity_id=entity.id,
                    )
                )
            elif (
                dated
                and dated.start_date is not None
                and dated.end_date is not None
                and dated.end_date < dated.start_date
            ):
                items.append(
                    ValidationItem(
                        severity="error",
                        code="contradictory_dates",
                        message=f"{entity.entity_type} ends before it starts.",
                        entity_id=entity.id,
                    )
                )
        preference = session.get(PreferenceVersion, candidate.current_preference_version_id)
        if preference:
            for item in preference.items:
                if item.state == "unknown":
                    items.append(
                        ValidationItem(
                            severity="info",
                            code="missing_preference",
                            message=f"Preference is unknown: {item.preference_type}.",
                            field=item.preference_type,
                        )
                    )
        for issue in parser_issues or []:
            items.append(
                ValidationItem(
                    severity=issue.get("severity", "warning"),
                    code=issue.get("code", "parser_issue"),
                    message=(
                        f"Resume parser issue: {issue.get('section', issue.get('code', 'unknown'))}"
                    ),
                )
            )
        total_checks = max(1, len(skills) + len(entities) + len(UNKNOWN_PREFERENCES))
        warnings = sum(item.severity != "info" for item in items)
        score = round(max(0.0, 1 - warnings / total_checks), 3)
        report = CompletenessReport(
            candidate_id=candidate.id,
            profile_version=version.version_number,
            completeness_score=score,
            items=items,
            created_at=datetime.now(UTC),
        )
        session.add(
            ValidationReport(
                candidate_id=candidate.id,
                profile_version_id=version.id,
                preference_version_id=candidate.current_preference_version_id,
                validator_version="1",
                completeness_score=score,
                items=[item.model_dump(mode="json") for item in items],
            )
        )
        return report

    def validate(self, candidate_id: str) -> CompletenessReport:
        with self.factory() as session, session.begin():
            candidate = session.get(Candidate, candidate_id)
            if not candidate or not candidate.current_profile_version_id:
                raise NotFoundError("Candidate profile not found")
            version = session.get(ProfileVersion, candidate.current_profile_version_id)
            assert version is not None
            return self._validate(session, candidate, version)

    def _result(
        self,
        session: Session,
        candidate: Candidate,
        version: ProfileVersion,
        noop: bool,
        report: CompletenessReport,
    ) -> IngestionResult:
        entity_count = (
            session.scalar(
                select(func.count(ProfileEntity.id)).where(
                    ProfileEntity.profile_version_id == version.id
                )
            )
            or 0
        )
        skill_count = (
            session.scalar(
                select(func.count(ProfileSkill.id)).where(
                    ProfileSkill.profile_version_id == version.id
                )
            )
            or 0
        )
        evidence_count = (
            session.scalar(
                select(func.count(EvidenceEdge.id))
                .join(ProfileSkill)
                .where(ProfileSkill.profile_version_id == version.id)
            )
            or 0
        )
        return IngestionResult(
            candidate_id=candidate.id,
            profile_version_id=version.id,
            version_number=version.version_number,
            semantic_noop=noop,
            entity_count=entity_count,
            skill_count=skill_count,
            evidence_count=evidence_count,
            validation=report,
        )

    def get_profile(self, candidate_id: str, include_private: bool = False) -> dict[str, Any]:
        with self.factory() as session:
            candidate = session.get(Candidate, candidate_id)
            if not candidate or not candidate.current_profile_version_id:
                raise NotFoundError("Candidate profile not found")
            version = session.get(ProfileVersion, candidate.current_profile_version_id)
            assert version is not None
            details = version.details
            entities = []
            for entity in sorted(version.entities, key=lambda row: row.display_order):
                subtype: Any = None
                if entity.entity_type == "experience":
                    subtype = session.get(Experience, entity.id)
                elif entity.entity_type == "project":
                    subtype = session.get(Project, entity.id)
                elif entity.entity_type == "education":
                    subtype = session.get(Education, entity.id)
                elif entity.entity_type == "contribution":
                    subtype = session.get(Contribution, entity.id)
                else:
                    subtype = session.get(Achievement, entity.id)
                data = {
                    column.name: getattr(subtype, column.name)
                    for column in subtype.__table__.columns
                }
                data.pop("entity_id", None)
                for key, value in list(data.items()):
                    if isinstance(value, (date, datetime)):
                        data[key] = value.isoformat()
                entities.append(
                    {
                        "id": entity.id,
                        "type": entity.entity_type,
                        "identity_key": entity.identity_key,
                        "verification_status": entity.verification_status,
                        "data": data,
                        "statements": [statement.text for statement in entity.statements],
                    }
                )
            skills = []
            for skill in version.skills:
                skills.append(
                    {
                        "name": skill.catalog.canonical_name,
                        "category": skill.catalog.category,
                        "proficiency": skill.candidate_proficiency,
                        "verification_status": skill.verification_status,
                        "evidence_count": len(skill.evidence),
                    }
                )
            output: dict[str, Any] = {
                "candidate_id": candidate.id,
                "display_name": candidate.display_name,
                "profile_version": version.version_number,
                "created_at": version.created_at.isoformat(),
                "summary": details.professional_summary if details else None,
                "entities": entities,
                "skills": sorted(skills, key=lambda row: row["name"].casefold()),
                "preferences": self._preferences_dict(session, candidate),
            }
            if include_private and details:
                output["contact"] = {
                    "email": details.email,
                    "phone": details.phone,
                    "linkedin_url": details.linkedin_url,
                    "github_url": details.github_url,
                }
            return output

    def _preferences_dict(self, session: Session, candidate: Candidate) -> dict[str, Any]:
        preference = session.get(PreferenceVersion, candidate.current_preference_version_id)
        if not preference:
            return {"version": None, "items": []}
        return {
            "version": preference.version_number,
            "items": [
                {
                    "type": item.preference_type,
                    "value": item.value,
                    "state": item.state,
                    "priority": item.priority,
                }
                for item in preference.items
            ],
        }

    def evidence_for_skill(self, candidate_id: str, skill_name: str) -> list[dict[str, Any]]:
        with self.factory() as session:
            candidate = session.get(Candidate, candidate_id)
            if not candidate or not candidate.current_profile_version_id:
                raise NotFoundError("Candidate profile not found")
            skill = session.scalar(
                select(ProfileSkill)
                .join(SkillCatalog)
                .where(
                    ProfileSkill.profile_version_id == candidate.current_profile_version_id,
                    func.lower(SkillCatalog.canonical_name) == skill_name.casefold(),
                )
            )
            if not skill:
                return []
            return [
                {
                    "classification": edge.classification,
                    "verification_status": edge.verification_status,
                    "confidence": edge.confidence,
                    "explanation": edge.explanation,
                    "entity_id": edge.entity_id,
                    "entity_type": edge.entity.entity_type,
                    "statement": edge.statement.text if edge.statement else None,
                }
                for edge in skill.evidence
            ]

    def diff(self, candidate_id: str, from_version: int, to_version: int) -> dict[str, Any]:
        with self.factory() as session:
            versions = {
                version.version_number: version
                for version in session.scalars(
                    select(ProfileVersion).where(
                        ProfileVersion.candidate_id == candidate_id,
                        ProfileVersion.version_number.in_([from_version, to_version]),
                    )
                )
            }
            if len(versions) != 2:
                raise NotFoundError("One or both profile versions were not found")

            def keys(version: ProfileVersion) -> set[str]:
                return {
                    f"{entity.entity_type}:{entity.identity_key}" for entity in version.entities
                }

            before, after = keys(versions[from_version]), keys(versions[to_version])
            return {
                "from": from_version,
                "to": to_version,
                "added": sorted(after - before),
                "removed": sorted(before - after),
                "unchanged": sorted(before & after),
            }
