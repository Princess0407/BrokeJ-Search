from brokej_search.database.models import Job
from brokej_search.discovery.deduplication import canonicalize_url, evaluate
from brokej_search.discovery.schemas import JobObservation


def _job(**changes):
    values = {
        "title": "Backend Engineer",
        "normalized_title": "backend engineer",
        "company_name": "Example",
        "normalized_company": "example",
        "description_text": "Build Python APIs and reliable distributed services",
        "listing_url": "https://jobs.example/1",
        "application_url": "https://jobs.example/1/apply",
        "canonical_application_url": "https://jobs.example/1/apply",
        "locations": ["Bengaluru"],
    }
    values.update(changes)
    return Job(**values)


def _observation(**changes):
    values = {
        "source_job_id": "other-1",
        "title": "Backend Engineer",
        "company_name": "Example",
        "description_text": "Build Python APIs and reliable distributed services",
        "listing_url": "https://other.example/1",
        "application_url": "https://jobs.example/1/apply?utm_source=board",
        "locations": ["Bengaluru"],
        "raw": {},
    }
    values.update(changes)
    return JobObservation(**values)


def test_job_specific_url_merges_and_tracking_is_removed() -> None:
    assert canonicalize_url(_observation().application_url) == "https://jobs.example/1/apply"
    assert evaluate(_job(), _observation()).outcome == "merge"


def test_title_alone_never_merges() -> None:
    result = evaluate(
        _job(company_name="Other", normalized_company="other", description_text="Unrelated role"),
        _observation(
            application_url="https://new.example/apply", description_text="Different work"
        ),
    )
    assert result.outcome == "separate"


def test_similar_but_uncertain_job_is_flagged() -> None:
    result = evaluate(
        _job(canonical_application_url=None),
        _observation(
            title="Backend Engineer II",
            application_url="https://other.example/apply/2",
            description_text="Build Python APIs and distributed platform services",
        ),
    )
    assert result.outcome in {"potential_duplicate", "separate"}
    assert result.confidence < 0.92
