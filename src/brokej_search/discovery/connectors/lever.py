from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

from brokej_search.core.exceptions import ConnectorSchemaError
from brokej_search.discovery.connectors.base import JobConnector
from brokej_search.discovery.connectors.utils import html_to_text, opportunity_type, parse_datetime
from brokej_search.discovery.schemas import ConnectorPage, JobObservation


class LeverConnector(JobConnector):
    connector_type = "lever"

    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> AsyncIterator[ConnectorPage]:
        page_size = min(int(self.config.get("page_size", 100)), 100)
        page_limit = int(self.config.get("page_limit", 20))
        skip = int((checkpoint or {}).get("skip", 0))
        region = self.config.get("region", "global")
        host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{self.board_identifier}"
        for _ in range(page_limit):
            payload, headers = await self.request_json(
                url, {"mode": "json", "skip": skip, "limit": page_size}
            )
            if not isinstance(payload, list):
                raise ConnectorSchemaError("Lever response must be a list")
            jobs = [self.normalize(item) for item in payload]
            next_skip = skip + len(payload)
            complete = len(payload) < page_size
            yield ConnectorPage(
                jobs=jobs,
                checkpoint={"skip": 0 if complete else next_skip, "complete": complete},
                complete=complete,
                response_hash=self.response_hash(payload),
                etag=headers.get("ETag"),
                last_modified=headers.get("Last-Modified"),
            )
            if complete:
                return
            skip = next_skip
        raise ConnectorSchemaError("Lever page limit reached before completion")

    def normalize(self, item: Any) -> JobObservation:
        if not isinstance(item, dict) or not item.get("id") or not item.get("text"):
            raise ConnectorSchemaError("Lever job is missing id or text")
        listing_url = item.get("hostedUrl") or item.get("applyUrl")
        if not listing_url:
            raise ConnectorSchemaError("Lever job is missing hosted/apply URL")
        categories_value = item.get("categories")
        categories = (
            cast(dict[str, Any], categories_value) if isinstance(categories_value, dict) else {}
        )
        all_locations = categories.get("allLocations")
        locations = (
            [str(value) for value in all_locations]
            if isinstance(all_locations, list)
            else ([str(categories["location"])] if categories.get("location") else [])
        )
        commitment = str(categories.get("commitment") or "unknown")
        employment = {
            "full-time": "full_time",
            "part-time": "part_time",
            "contract": "contract",
            "internship": "internship",
        }.get(commitment.casefold(), "unknown")
        description_html = item.get("description") or item.get("additional")
        description_text = item.get("descriptionPlain") or html_to_text(description_html)
        if isinstance(item.get("lists"), list):
            extra = "\n".join(
                f"{entry.get('text', '')}\n{html_to_text(entry.get('content'))}"
                for entry in item["lists"]
                if isinstance(entry, dict)
            )
            description_text = f"{description_text}\n{extra}".strip()
        return JobObservation(
            source_job_id=str(item["id"]),
            title=str(item["text"]),
            company_name=self.company_name,
            company_website=self.config.get("company_website"),
            description_text=str(description_text or ""),
            description_html=str(description_html) if description_html else None,
            listing_url=str(listing_url),
            application_url=str(item.get("applyUrl") or listing_url),
            locations=locations,
            work_arrangement="remote"
            if any("remote" in loc.casefold() for loc in locations)
            else "unknown",
            employment_type=employment,
            opportunity_type=opportunity_type(str(item["text"]), employment),
            posting_date=parse_datetime(item.get("createdAt")),
            raw=item,
            field_origins={
                "title": "source_stated",
                "description_text": "source_stated",
                "locations": "source_stated",
                "employment_type": "source_stated",
                "work_arrangement": "parser_extracted",
                "opportunity_type": "parser_extracted",
            },
        )
