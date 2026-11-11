from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from brokej_search.core.exceptions import (
    ConnectorError,
    ConnectorSchemaError,
    GitHubRateLimitError,
)
from brokej_search.core.http import retry_after_seconds


class GitHubClient:
    base_url = "https://api.github.com"

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_attempts: int = 3,
    ) -> None:
        self.client = client
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BrokeJ-Search/0.2 (+evidence-analysis)",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    async def get_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
    ) -> tuple[Any | None, httpx.Headers]:
        url = self._url(path_or_url)
        headers = dict(self.headers)
        if etag:
            headers["If-None-Match"] = etag
        for attempt in range(self.max_attempts):
            try:
                response = await self.client.get(url, params=params, headers=headers)
            except httpx.RequestError as exc:
                if attempt + 1 == self.max_attempts:
                    raise ConnectorError(f"GitHub request failed: {type(exc).__name__}") from exc
                await self.sleep(0.2 * (2**attempt))
                continue
            if response.status_code == 304:
                return None, response.headers
            if response.status_code == 403:
                if response.headers.get("x-ratelimit-remaining") == "0":
                    raise GitHubRateLimitError(
                        "GitHub rate limit reached; "
                        f"reset={response.headers.get('x-ratelimit-reset', 'unknown')}"
                    )
                retry_after = retry_after_seconds(response.headers.get("retry-after"))
                if retry_after is not None:
                    if attempt + 1 == self.max_attempts:
                        raise ConnectorError("GitHub secondary rate limit retry exhausted")
                    await self.sleep(retry_after)
                    continue
            if response.status_code in {408, 429, 500, 502, 503, 504}:
                if attempt + 1 == self.max_attempts:
                    raise ConnectorError(f"Temporary GitHub response: HTTP {response.status_code}")
                delay = retry_after_seconds(response.headers.get("retry-after"))
                if delay is None:
                    delay = 0.2 * (2**attempt)
                await self.sleep(min(delay, 60))
                continue
            if response.status_code == 404:
                return None, response.headers
            if response.status_code >= 400:
                raise ConnectorError(f"GitHub rejected request: HTTP {response.status_code}")
            try:
                return response.json(), response.headers
            except ValueError as exc:
                raise ConnectorSchemaError("GitHub response is not valid JSON") from exc
        raise ConnectorError("GitHub request attempts exhausted")

    async def paginated(
        self, path: str, *, params: dict[str, Any] | None = None, max_items: int = 100
    ) -> list[dict[str, Any]]:
        url: str | None = path
        query: dict[str, Any] | None = {"per_page": min(max_items, 100), **(params or {})}
        items: list[dict[str, Any]] = []
        while url and len(items) < max_items:
            payload, headers = await self.get_json(url, params=query)
            if payload is None:
                break
            if not isinstance(payload, list):
                raise ConnectorSchemaError("Expected a paginated GitHub list")
            if any(not isinstance(item, dict) for item in payload):
                raise ConnectorSchemaError("GitHub list item must be an object")
            items.extend(payload)
            next_url = response_next(headers)
            url = next_url
            query = None
        return items[:max_items]

    async def paginated_search(
        self, path: str, *, params: dict[str, Any], max_items: int = 90
    ) -> list[dict[str, Any]]:
        url: str | None = path
        query: dict[str, Any] | None = {
            "per_page": min(max_items, 100),
            **params,
        }
        items: list[dict[str, Any]] = []
        while url and len(items) < max_items:
            payload, headers = await self.get_json(url, params=query)
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ConnectorSchemaError("Expected a GitHub search result with an items list")
            if any(not isinstance(item, dict) for item in payload["items"]):
                raise ConnectorSchemaError("GitHub search item must be an object")
            items.extend(payload["items"])
            url = response_next(headers)
            query = None
        return items[:max_items]

    def _url(self, path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != "api.github.com":
            raise ConnectorError("Refusing a non-GitHub API URL")
        return url


def response_next(headers: httpx.Headers) -> str | None:
    link = headers.get("link", "")
    for part in link.split(","):
        if 'rel="next"' in part:
            match = part.strip().split(";", 1)[0].strip()
            return match[1:-1] if match.startswith("<") and match.endswith(">") else None
    return None
