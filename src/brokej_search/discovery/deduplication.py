from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from brokej_search.database.models import Job
from brokej_search.discovery.schemas import JobObservation

TRACKING_PARAMETERS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "source",
    "ref",
}


def normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def canonicalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if k.casefold() not in TRACKING_PARAMETERS]
    )
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, query, ""))


def is_job_specific_url(value: str | None) -> bool:
    if not value:
        return False
    parts = urlsplit(value)
    segments = [part for part in parts.path.split("/") if part]
    return len(segments) >= 2 or bool(re.search(r"(?:job|jid|gh_jid|posting)=", parts.query, re.I))


def description_similarity(left: str, right: str) -> float:
    left_words = set(normalize_text(left).split())
    right_words = set(normalize_text(right).split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


@dataclass(frozen=True)
class DedupResult:
    confidence: float
    outcome: str
    signals: dict[str, object]


def evaluate(existing: Job, observed: JobObservation) -> DedupResult:
    company_equal = existing.normalized_company == normalize_text(observed.company_name)
    title_equal = existing.normalized_title == normalize_text(observed.title)
    title_ratio = SequenceMatcher(
        None, existing.normalized_title, normalize_text(observed.title)
    ).ratio()
    location_overlap = bool(
        {normalize_text(value) for value in existing.locations}
        & {normalize_text(value) for value in observed.locations}
    )
    description = description_similarity(existing.description_text, observed.description_text)
    observed_url = canonicalize_url(observed.application_url)
    url_equal = bool(
        observed_url
        and existing.canonical_application_url == observed_url
        and is_job_specific_url(observed_url)
    )
    signals: dict[str, object] = {
        "company_equal": company_equal,
        "title_equal": title_equal,
        "title_similarity": round(title_ratio, 3),
        "location_overlap": location_overlap,
        "description_similarity": round(description, 3),
        "job_specific_url_equal": url_equal,
    }
    if url_equal:
        return DedupResult(1.0, "merge", signals)
    if (
        company_equal
        and title_equal
        and description >= 0.7
        and (location_overlap or not existing.locations or not observed.locations)
    ):
        return DedupResult(0.92, "merge", signals)
    score = (
        (0.3 if company_equal else 0)
        + (0.3 * title_ratio)
        + (0.15 if location_overlap else 0)
        + (0.25 * description)
    )
    if score >= 0.65:
        return DedupResult(round(score, 3), "potential_duplicate", signals)
    return DedupResult(round(score, 3), "separate", signals)
