from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import SummaryResult, Tweet


class Storage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_tweets (
                tweet_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                text TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                summary_title TEXT NOT NULL,
                summary_body TEXT NOT NULL,
                summary_tags TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.connection.commit()

    def has_tweet(self, tweet_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM processed_tweets WHERE tweet_id = ?",
            (tweet_id,),
        ).fetchone()
        return row is not None

    def save_tweet(self, tweet: Tweet, summary: SummaryResult) -> None:
        self.connection.execute(
            """
            INSERT INTO processed_tweets (
                tweet_id,
                username,
                text,
                url,
                published_at,
                summary_title,
                summary_body,
                summary_tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tweet.tweet_id,
                tweet.username,
                tweet.text,
                tweet.url,
                tweet.published_at,
                summary.title,
                summary.body,
                ",".join(summary.tags),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
