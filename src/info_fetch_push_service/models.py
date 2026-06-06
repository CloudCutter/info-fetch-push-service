from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Tweet:
    tweet_id: str
    username: str
    display_name: str | None
    text: str
    url: str
    published_at: str
    replying_to: list[str] | None = None
    quoted_username: str | None = None
    quoted_display_name: str | None = None
    quoted_text: str | None = None


@dataclass(slots=True)
class SummaryResult:
    title: str
    body: str
    tags: list[str]
    translation: str | None = None


@dataclass(slots=True)
class DigestWindow:
    start_label: str
    end_label: str
    tweet_count: int
