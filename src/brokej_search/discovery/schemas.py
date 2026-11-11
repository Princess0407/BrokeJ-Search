from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobObservation(BaseModel):
    source_job_id: str
    title: str
    company_name: str
    company_website: str | None = None
    description_text: str = ""
    description_html: str | None = None
    listing_url: str
    application_url: str | None = None
    locations: list[str] = Field(default_factory=list)
    work_arrangement: str = "unknown"
    employment_type: str = "unknown"
    opportunity_type: str = "unknown"
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirements: str | None = None
    education_requirements: str | None = None
    graduation_year_restrictions: str | None = None
    compensation: dict[str, Any] | None = None
    posting_date: datetime | None = None
    application_deadline: datetime | None = None
    raw: dict[str, Any]
    field_origins: dict[str, str] = Field(default_factory=dict)


class ConnectorPage(BaseModel):
    jobs: list[JobObservation]
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    complete: bool = True
    response_hash: str | None = None
    etag: str | None = None
    last_modified: str | None = None


class SourceCreate(BaseModel):
    name: str
    connector_type: str
    board_identifier: str
    company_name: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class DiscoverySummary(BaseModel):
    run_id: str
    status: str
    sources_succeeded: int
    sources_failed: int
    fetched: int
    created: int
    updated: int
