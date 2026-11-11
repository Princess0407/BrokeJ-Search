from datetime import UTC, datetime
from email.utils import format_datetime

from brokej_search.core.http import retry_after_seconds


def test_retry_after_delta_and_http_date_are_bounded() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    assert retry_after_seconds("2", now=now) == 2
    assert retry_after_seconds(format_datetime(now.replace(second=5)), now=now) == 5
    assert retry_after_seconds("120", now=now) == 60
    assert retry_after_seconds("invalid", now=now) is None
