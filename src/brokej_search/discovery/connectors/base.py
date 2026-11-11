from __future__ import annotations

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from brokej_search.core.exceptions import ConnectorError, ConnectorSchemaError
from brokej_search.discovery.schemas import ConnectorPage


class JobConnector(ABC):
    connector_type: str

    def __init__(
        self,
        client: httpx.AsyncClient,
        board_identifier: str,
        company_name: str,
        config: dict[str, Any] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.board_identifier = board_identifier
        self.company_name = company_name
        self.config = config or {}
        self.sleep = sleep
        self._last_request_started: float | None = None

    async def request_json(
        self, url: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, httpx.Headers]:
        attempts = int(self.config.get("max_attempts", 3))
        base_delay = float(self.config.get("retry_base_seconds", 0.2))
        minimum_interval = float(self.config.get("min_request_interval_seconds", 1.0))
        for attempt in range(attempts):
            if self._last_request_started is not None:
                remaining = minimum_interval - (time.monotonic() - self._last_request_started)
                if remaining > 0:
                    await self.sleep(remaining)
            self._last_request_started = time.monotonic()
            try:
                response = await self.client.get(url, params=params)
            except httpx.RequestError as exc:
                if attempt + 1 == attempts:
                    raise ConnectorError(f"Network request failed: {type(exc).__name__}") from exc
                await self.sleep(base_delay * (2**attempt))
                continue
            if response.status_code == 429 or response.status_code in {408, 500, 502, 503, 504}:
                if attempt + 1 == attempts:
                    raise ConnectorError(
                        f"Temporary provider response: HTTP {response.status_code}"
                    )
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else base_delay * (2**attempt)
                )
                await self.sleep(min(delay, 60))
                continue
            if response.status_code >= 400:
                raise ConnectorError(f"Provider rejected request: HTTP {response.status_code}")
            try:
                return response.json(), response.headers
            except ValueError as exc:
                raise ConnectorSchemaError("Provider response is not valid JSON") from exc
        raise ConnectorError("Request attempts exhausted")

    @staticmethod
    def response_hash(payload: Any) -> str:
        value = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()

    @abstractmethod
    async def fetch(self, checkpoint: dict[str, Any] | None = None) -> AsyncIterator[ConnectorPage]:
        if False:
            yield ConnectorPage(jobs=[])
