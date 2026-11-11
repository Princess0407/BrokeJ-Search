import asyncio

import httpx
from sqlalchemy import func, select

from brokej_search.core.exceptions import ConnectorError
from brokej_search.database.models import (
    Job,
    JobFieldObservation,
    JobLocation,
    JobSourceAppearance,
    RetryItem,
    SourceCheckpoint,
    utcnow,
)
from brokej_search.discovery.connectors.base import JobConnector
from brokej_search.discovery.schemas import ConnectorPage, JobObservation, SourceCreate


class StaticConnector(JobConnector):
    connector_type = "test"

    def __init__(self, pages, fail_after: int | None = None):
        super().__init__(httpx.AsyncClient(), "test", "Example")
        self.pages = pages
        self.fail_after = fail_after
        self.received_checkpoint = None

    async def fetch(self, checkpoint=None):
        self.received_checkpoint = checkpoint
        for index, page in enumerate(self.pages):
            if self.fail_after is not None and index >= self.fail_after:
                raise ConnectorError("temporary failure")
            yield page
        if self.fail_after is not None and self.fail_after >= len(self.pages):
            raise ConnectorError("temporary failure")


def observation(source_id="job-1", title="Backend Engineer", application_url=None):
    return JobObservation(
        source_job_id=source_id,
        title=title,
        company_name="Example",
        description_text="Build Python APIs and reliable distributed systems.",
        listing_url=f"https://listings.example/{source_id}",
        application_url=application_url or f"https://apply.example/{source_id}",
        locations=["Bengaluru"],
        employment_type="full_time",
        opportunity_type="full_time",
        raw={"id": source_id, "title": title},
        field_origins={"title": "source_stated"},
    )


def add_source(runtime, name="source"):
    return runtime.discovery.add_source(
        SourceCreate(
            name=name,
            connector_type="greenhouse",
            board_identifier=name,
            company_name="Example",
        )
    )


def test_repeated_discovery_is_idempotent(runtime) -> None:
    source_id = add_source(runtime)
    connector = StaticConnector(
        [ConnectorPage(jobs=[observation()], checkpoint={"complete": True})]
    )
    first = asyncio.run(runtime.discovery.run(connector_overrides={source_id: connector}))
    second = asyncio.run(runtime.discovery.run(connector_overrides={source_id: connector}))
    with runtime.factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(JobSourceAppearance.id))) == 1
        assert session.scalar(select(func.count(JobLocation.id))) == 1
        assert session.scalar(select(func.count(JobFieldObservation.id))) == 1
    assert first.created == 1
    assert second.updated == 1


def test_duplicate_across_sources_preserves_provenance(runtime) -> None:
    first_source = add_source(runtime, "first")
    second_source = add_source(runtime, "second")
    common_url = "https://company.example/jobs/backend/apply"
    connectors = {
        first_source: StaticConnector(
            [ConnectorPage(jobs=[observation("first-1", application_url=common_url)])]
        ),
        second_source: StaticConnector(
            [ConnectorPage(jobs=[observation("second-1", application_url=common_url)])]
        ),
    }
    summary = asyncio.run(runtime.discovery.run(connector_overrides=connectors))
    with runtime.factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(JobSourceAppearance.id))) == 2
    assert summary.sources_succeeded == 2


def test_failed_source_does_not_rollback_successful_source(runtime) -> None:
    good_source = add_source(runtime, "good")
    bad_source = add_source(runtime, "bad")
    connectors = {
        good_source: StaticConnector([ConnectorPage(jobs=[observation()])]),
        bad_source: StaticConnector([], fail_after=0),
    }
    summary = asyncio.run(runtime.discovery.run(connector_overrides=connectors))
    with runtime.factory() as session:
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(RetryItem.id))) == 1
    assert summary.status == "partial"
    assert summary.sources_succeeded == summary.sources_failed == 1


def test_due_retry_is_recovered_and_closed(runtime) -> None:
    source_id = add_source(runtime)
    failed = StaticConnector([], fail_after=0)
    asyncio.run(runtime.discovery.run(connector_overrides={source_id: failed}))
    with runtime.factory() as session, session.begin():
        retry = session.scalar(select(RetryItem))
        retry.next_attempt_at = utcnow()
    recovered = StaticConnector([ConnectorPage(jobs=[observation()])])
    result = asyncio.run(
        runtime.discovery.run_due_retries(connector_overrides={source_id: recovered})
    )
    with runtime.factory() as session:
        assert session.scalar(select(RetryItem.status)) == "succeeded"
    assert result is not None
    assert result.status == "succeeded"


def test_checkpoint_survives_interruption(runtime) -> None:
    source_id = add_source(runtime)
    first_page = ConnectorPage(
        jobs=[observation()], checkpoint={"cursor": "page-2"}, complete=False
    )
    failing = StaticConnector([first_page], fail_after=1)
    first = asyncio.run(runtime.discovery.run(connector_overrides={source_id: failing}))
    resumed = StaticConnector(
        [
            ConnectorPage(
                jobs=[observation("job-2", title="Platform Engineer")],
                checkpoint={"complete": True},
            )
        ]
    )
    second = asyncio.run(runtime.discovery.run(connector_overrides={source_id: resumed}))
    with runtime.factory() as session:
        checkpoint = session.get(SourceCheckpoint, source_id)
        assert checkpoint.value == {"complete": True}
        assert session.scalar(select(func.count(Job.id))) == 2
    assert first.status == "failed"
    assert resumed.received_checkpoint == {"cursor": "page-2"}
    assert second.status == "succeeded"


def test_listing_expires_only_after_two_successful_omissions(runtime) -> None:
    source_id = add_source(runtime)
    asyncio.run(
        runtime.discovery.run(
            connector_overrides={source_id: StaticConnector([ConnectorPage(jobs=[observation()])])}
        )
    )
    empty = StaticConnector([ConnectorPage(jobs=[])])
    asyncio.run(runtime.discovery.run(connector_overrides={source_id: empty}))
    with runtime.factory() as session:
        assert session.scalar(select(Job.status)) == "active"
    asyncio.run(runtime.discovery.run(connector_overrides={source_id: empty}))
    with runtime.factory() as session:
        assert session.scalar(select(Job.status)) == "expired"
