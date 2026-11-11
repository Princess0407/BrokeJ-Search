import asyncio
import json
from pathlib import Path

import httpx
import pytest

from brokej_search.core.exceptions import ConnectorError, ConnectorSchemaError
from brokej_search.discovery.connectors import AshbyConnector, GreenhouseConnector, LeverConnector


def _client(payloads: list[object], statuses: list[int] | None = None) -> httpx.AsyncClient:
    calls = 0
    statuses = statuses or [200] * len(payloads)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        index = min(calls, len(payloads) - 1)
        calls += 1
        return httpx.Response(statuses[index], json=payloads[index])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _pages(connector):
    return [page async for page in connector.fetch()]


def test_greenhouse_fixture(fixture_dir: Path) -> None:
    payload = json.loads((fixture_dir / "greenhouse.json").read_text())

    async def run():
        async with _client([payload]) as client:
            pages = await _pages(GreenhouseConnector(client, "example", "Example"))
            assert pages[0].jobs[0].opportunity_type == "internship"
            assert pages[0].jobs[0].locations == ["Remote - India"]
            assert "model serving" in pages[0].jobs[0].description_text

    asyncio.run(run())


def test_lever_pagination(fixture_dir: Path) -> None:
    payload = json.loads((fixture_dir / "lever_page_1.json").read_text())

    async def run():
        async with _client([payload, []]) as client:
            connector = LeverConnector(
                client,
                "example",
                "Example",
                {
                    "page_size": 2,
                    "retry_base_seconds": 0,
                    "min_request_interval_seconds": 0,
                },
            )
            pages = await _pages(connector)
            assert len(pages) == 2
            assert pages[0].jobs[0].employment_type == "full_time"
            assert pages[0].jobs[1].opportunity_type == "internship"
            assert pages[-1].checkpoint["complete"] is True

    asyncio.run(run())


def test_ashby_fixture_filters_unlisted(fixture_dir: Path) -> None:
    payload = json.loads((fixture_dir / "ashby.json").read_text())

    async def run():
        async with _client([payload]) as client:
            pages = await _pages(AshbyConnector(client, "example", "Example"))
            assert len(pages[0].jobs) == 1
            job = pages[0].jobs[0]
            assert job.work_arrangement == "hybrid"
            assert job.compensation["summaryComponents"][0]["currencyCode"] == "INR"

    asyncio.run(run())


def test_malformed_provider_response_is_rejected() -> None:
    async def run():
        async with _client([{"not_jobs": []}]) as client:
            with pytest.raises(ConnectorSchemaError):
                await _pages(GreenhouseConnector(client, "example", "Example"))

    asyncio.run(run())


def test_temporary_failure_retries_then_succeeds() -> None:
    payload = {"jobs": []}

    async def no_sleep(_delay: float) -> None:
        return None

    async def run():
        async with _client([{}, payload], [429, 200]) as client:
            pages = await _pages(
                GreenhouseConnector(
                    client,
                    "example",
                    "Example",
                    {
                        "retry_base_seconds": 0,
                        "min_request_interval_seconds": 0,
                    },
                    sleep=no_sleep,
                )
            )
            assert pages[0].jobs == []

    asyncio.run(run())


def test_non_retryable_failure_surfaces() -> None:
    async def run():
        async with _client([{}], [403]) as client:
            with pytest.raises(ConnectorError, match="HTTP 403"):
                await _pages(GreenhouseConnector(client, "example", "Example"))

    asyncio.run(run())
