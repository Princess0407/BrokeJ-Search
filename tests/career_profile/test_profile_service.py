from pathlib import Path

from sqlalchemy import func, select

from brokej_search.database.models import PreferenceVersion, ProfileVersion, SourceDocument


def test_resume_ingestion_is_versioned_and_idempotent(runtime, resume_path: Path) -> None:
    first = runtime.profiles.ingest_resume("candidate", resume_path)
    second = runtime.profiles.ingest_resume("candidate", resume_path)

    assert first.version_number == 1
    assert first.semantic_noop is False
    assert second.semantic_noop is True
    assert first.entity_count >= 9
    assert first.skill_count >= 20
    assert first.evidence_count > 0
    with runtime.factory() as session:
        assert session.scalar(select(func.count(ProfileVersion.id))) == 1
        assert session.scalar(select(func.count(SourceDocument.id))) == 1


def test_profile_evidence_and_private_contact_boundary(runtime, resume_path: Path) -> None:
    runtime.profiles.ingest_resume("candidate", resume_path)
    profile = runtime.profiles.get_profile("candidate")
    evidence = runtime.profiles.evidence_for_skill("candidate", "Python")

    assert "contact" not in profile
    assert profile["profile_version"] == 1
    assert any(item["type"] == "experience" for item in profile["entities"])
    assert evidence
    assert {item["classification"] for item in evidence} == {"direct"}
    assert all(item["verification_status"] == "resume_extracted" for item in evidence)


def test_validation_reports_unknowns_and_unverified_skills(runtime, resume_path: Path) -> None:
    runtime.profiles.ingest_resume("candidate", resume_path)
    report = runtime.profiles.validate("candidate")
    codes = {item.code for item in report.items}
    assert "missing_preference" in codes
    assert "skill_without_evidence" in codes
    assert 0 <= report.completeness_score <= 1


def test_preferences_version_independently(runtime, resume_path: Path) -> None:
    runtime.profiles.ingest_resume("candidate", resume_path)
    profile_before = runtime.profiles.get_profile("candidate")
    preference_id = runtime.profiles.update_preferences(
        "candidate",
        [
            {
                "preference_type": "work_arrangement",
                "value": "remote",
                "state": "prefer",
                "priority": 1,
            }
        ],
    )
    profile_after = runtime.profiles.get_profile("candidate")
    with runtime.factory() as session:
        preference = session.get(PreferenceVersion, preference_id)
        assert preference.version_number == 2
    assert profile_before["profile_version"] == profile_after["profile_version"] == 1
    assert profile_after["preferences"]["version"] == 2
