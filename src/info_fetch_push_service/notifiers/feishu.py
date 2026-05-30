from __future__ import annotations

import base64
import hashlib
import hmac
import time

import httpx

from ..models import SummaryResult, Tweet


class FeishuNotifier:
    def __init__(self, webhook_url: str, secret: str | None = None, mention_all: bool = False) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.mention_all = mention_all

    def send_tweet_summary(self, tweet: Tweet, summary: SummaryResult) -> None:
        text = self._format_text(tweet, summary)
        payload = {
            "msg_type": "text",
            "content": {
                "text": text,
            },
        }

        if self.secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._sign(timestamp, self.secret)

        response = httpx.post(self.webhook_url, json=payload, timeout=30.0)
        response.raise_for_status()
        body = response.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"Feishu webhook failed: {body}")

    def _format_text(self, tweet: Tweet, summary: SummaryResult) -> str:
        tags = " / ".join(summary.tags) if summary.tags else "summary"
        mention = " <at user_id=\"all\">all</at>" if self.mention_all else ""
        return (
            f"[{summary.title}]{mention}\n"
            f"Author: @{tweet.username}\n"
            f"Time: {tweet.published_at or 'unknown'}\n"
            f"Tags: {tags}\n"
            f"Summary: {summary.body}\n"
            f"Source: {tweet.url}"
        )

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")
