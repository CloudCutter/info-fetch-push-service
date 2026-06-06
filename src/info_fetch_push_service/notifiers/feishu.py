from __future__ import annotations

import base64
import hashlib
import hmac
import time

import httpx

from ..models import DigestWindow, SummaryResult, Tweet


class FeishuNotifier:
    def __init__(self, webhook_url: str, secret: str | None = None, mention_all: bool = False) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.mention_all = mention_all

    def send_tweet_summary(self, tweet: Tweet, summary: SummaryResult) -> None:
        self._send_text(self._format_text(tweet, summary))

    def send_digest_summaries(
        self,
        username: str,
        tweet_summaries: list[tuple[Tweet, SummaryResult]],
        window: DigestWindow,
    ) -> None:
        if not tweet_summaries:
            return

        chunks: list[str] = []
        current_lines = [
            f"[夜间汇总] @{username}",
            f"时间窗：{window.start_label} - {window.end_label}",
            f"推文数：{window.tweet_count}",
            "",
        ]

        for index, (tweet, summary) in enumerate(tweet_summaries, start=1):
            section = self._format_digest_item(index, tweet, summary)
            candidate = "\n".join(current_lines + [section])
            if len(candidate) > 2600 and len(current_lines) > 4:
                chunks.append("\n".join(current_lines).rstrip())
                current_lines = [
                    f"[夜间汇总续] @{username}",
                    f"时间窗：{window.start_label} - {window.end_label}",
                    "",
                    section,
                ]
            else:
                current_lines.append(section)
                current_lines.append("")

        final_chunk = "\n".join(current_lines).rstrip()
        if final_chunk:
            chunks.append(final_chunk)

        for chunk in chunks:
            self._send_text(chunk)

    def _send_text(self, text: str) -> None:
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
        author_label = tweet.display_name or tweet.username
        lines = [
            f"[{summary.title}]{mention}",
            f"作者：{author_label} (@{tweet.username})",
            f"时间：{tweet.published_at or 'unknown'}",
            f"标签：{tags}",
            f"推文翻译：{summary.translation or tweet.text}",
        ]

        context_lines = self._format_context_lines(tweet)
        if context_lines:
            lines.extend(context_lines)

        lines.extend(
            [
                f"点评：{summary.body}",
                f"原链接：{tweet.url}",
            ]
        )
        return "\n".join(lines)

    def _format_digest_item(self, index: int, tweet: Tweet, summary: SummaryResult) -> str:
        lines = [
            f"{index}. [{summary.title}]",
            f"作者：{tweet.display_name or tweet.username} (@{tweet.username})",
            f"时间：{tweet.published_at or 'unknown'}",
            f"标签：{' / '.join(summary.tags) if summary.tags else 'summary'}",
            f"推文翻译：{summary.translation or tweet.text}",
        ]
        lines.extend(self._format_context_lines(tweet))
        lines.extend(
            [
                f"点评：{summary.body}",
                f"原链接：{tweet.url}",
            ]
        )
        return "\n".join(lines)

    def _format_context_lines(self, tweet: Tweet) -> list[str]:
        lines: list[str] = []
        if tweet.replying_to:
            lines.append("回复对象：" + ", ".join(f"@{name}" for name in tweet.replying_to))
        if tweet.quoted_text:
            quoted_author = tweet.quoted_display_name or tweet.quoted_username or "unknown"
            quoted_handle = f" (@{tweet.quoted_username})" if tweet.quoted_username else ""
            lines.append(f"引用推文作者：{quoted_author}{quoted_handle}")
            lines.append(f"引用推文内容：{tweet.quoted_text}")
        return lines

    def _sign(self, timestamp: str, secret: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")
