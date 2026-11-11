from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from brokej_search.core.exceptions import ConnectorSchemaError
from brokej_search.discovery.connectors.base import JobConnector
from brokej_search.discovery.connectors.utils import opportunity_type, parse_datetime
from brokej_search.discovery.schemas import ConnectorPage, JobObservation


class AshbyConnector(JobConnector):
    connector_type = "ashby"

    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> AsyncIterator[ConnectorPage]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.board_identifier}"
        include_compensation = str(self.config.get("include_compensation", True)).lower()
        payload, headers = await self.request_json(
            url, {"includeCompensation": include_compensation}
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ConnectorSchemaError("Ashby response must contain a jobs list")
        jobs = []
        for item in payload["jobs"]:
            if not isinstance(item, dict):
                raise ConnectorSchemaError("Ashby job must be an object")
            if item.get("isListed", True):
                jobs.append(self.normalize(item))
        yield ConnectorPage(
            jobs=jobs,
            checkpoint={"complete": True, "count": len(jobs)},
            response_hash=self.response_hash(payload),
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
        )

    def normalize(self, item: Any) -> JobObservation:
        if not isinstance(item, dict) or not item.get("title") or not item.get("jobUrl"):
            raise ConnectorSchemaError("Ashby job is missing title or jobUrl")
        locations: list[str] = []
        if item.get("location"):
            locations.append(str(item["location"]))
        secondary_locations = item.get("secondaryLocations") or []
        if not isinstance(secondary_locations, list):
            raise ConnectorSchemaError("Ashby secondaryLocations must be a list")
        for secondary in secondary_locations:
            if isinstance(secondary, dict) and secondary.get("location"):
                locations.append(str(secondary["location"]))
        workplace = str(item.get("workplaceType") or "unknown")
        work_arrangement = {
            "remote": "remote",
            "hybrid": "hybrid",
            "onsite": "onsite",
        }.get(workplace.casefold(), "unknown")
        raw_employment = str(item.get("employmentType") or "unknown")
        employment = {
            "fulltime": "full_time",
            "parttime": "part_time",
            "intern": "internship",
            "contract": "contract",
            "temporary": "temporary",
        }.get(raw_employment.casefold(), "unknown")
        job_url = str(item["jobUrl"])
        return JobObservation(
            source_job_id=job_url,
            title=str(item["title"]),
            company_name=self.company_name,
            company_website=self.config.get("company_website"),
            description_text=str(item.get("descriptionPlain") or ""),
            description_html=str(item["descriptionHtml"]) if item.get("descriptionHtml") else None,
            listing_url=job_url,
            application_url=str(item.get("applyUrl") or job_url),
            locations=locations,
            work_arrangement=work_arrangement,
            employment_type=employment,
            opportunity_type=opportunity_type(str(item["title"]), employment),
            compensation=item.get("compensation")
            if isinstance(item.get("compensation"), dict)
            else None,
            posting_date=parse_datetime(item.get("publishedAt")),
            raw=item,
            field_origins={
                "title": "source_stated",
                "description_text": "source_stated",
                "locations": "source_stated",
                "employment_type": "source_stated",
                "work_arrangement": "source_stated",
                "compensation": "source_stated",
                "opportunity_type": "parser_extracted",
            },
        )
