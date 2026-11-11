from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from brokej_search.core.exceptions import ConnectorSchemaError
from brokej_search.discovery.connectors.base import JobConnector
from brokej_search.discovery.connectors.utils import html_to_text, opportunity_type, parse_datetime
from brokej_search.discovery.schemas import ConnectorPage, JobObservation


class GreenhouseConnector(JobConnector):
    connector_type = "greenhouse"

    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> AsyncIterator[ConnectorPage]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_identifier}/jobs"
        payload, headers = await self.request_json(url, {"content": "true"})
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ConnectorSchemaError("Greenhouse response must contain a jobs list")
        jobs = [self.normalize(item) for item in payload["jobs"]]
        yield ConnectorPage(
            jobs=jobs,
            checkpoint={"complete": True, "count": len(jobs)},
            response_hash=self.response_hash(payload),
            etag=headers.get("ETag"),
            last_modified=headers.get("Last-Modified"),
        )

    def normalize(self, item: Any) -> JobObservation:
        if (
            not isinstance(item, dict)
            or not item.get("id")
            or not item.get("title")
            or not item.get("absolute_url")
        ):
            raise ConnectorSchemaError("Greenhouse job is missing id, title, or absolute_url")
        location = item.get("location") or {}
        locations = (
            [location["name"]] if isinstance(location, dict) and location.get("name") else []
        )
        content = item.get("content") or ""
        item.get("metadata") if isinstance(item.get("metadata"), list) else []
        return JobObservation(
            source_job_id=str(item["id"]),
            title=str(item["title"]),
            company_name=self.company_name,
            company_website=self.config.get("company_website"),
            description_text=html_to_text(content),
            description_html=content or None,
            listing_url=str(item["absolute_url"]),
            application_url=str(item["absolute_url"]),
            locations=locations,
            work_arrangement="remote"
            if any("remote" in loc.casefold() for loc in locations)
            else "unknown",
            employment_type="unknown",
            opportunity_type=opportunity_type(str(item["title"]), "unknown"),
            compensation={"pay_ranges": item.get("pay_input_ranges")}
            if item.get("pay_input_ranges")
            else None,
            posting_date=parse_datetime(item.get("first_published") or item.get("updated_at")),
            application_deadline=parse_datetime(item.get("application_deadline")),
            raw=item,
            field_origins={
                "title": "source_stated",
                "description_text": "source_stated",
                "locations": "source_stated",
                "work_arrangement": "parser_extracted",
                "opportunity_type": "parser_extracted",
            },
        )
