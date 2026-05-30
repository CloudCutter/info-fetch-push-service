from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Tweet:
    tweet_id: str
    username: str
    text: str
    url: str
    published_at: str


@dataclass(slots=True)
class SummaryResult:
    title: str
    body: str
    tags: list[str]


@dataclass(slots=True)
class DigestWindow:
    start_label: str
    end_label: str
    tweet_count: int
