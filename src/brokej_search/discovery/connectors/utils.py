from __future__ import annotations

import html
from datetime import UTC, datetime
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(html.unescape(html.unescape(value)))
    return "\n".join(parser.parts)


def parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def opportunity_type(title: str, employment_type: str) -> str:
    combined = f"{title} {employment_type}".casefold()
    if "intern" in combined:
        return "internship"
    if "research" in combined:
        return "research"
    if employment_type in {"full_time", "fulltime", "full-time"}:
        return "full_time"
    return "unknown"
