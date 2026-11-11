from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
        return min(delay, 60) if delay >= 0 else None
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return min(max(0.0, (retry_at - current).total_seconds()), 60)
