from __future__ import annotations

import json
import logging
import time

import httpx

from ..models import DigestWindow, SummaryResult, Tweet

logger = logging.getLogger(__name__)


class DeepSeekSummarizer:
    def __init__(self, api_key: str, base_url: str, model: str, style_prompt: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.style_prompt = style_prompt

    def summarize(self, tweet: Tweet) -> SummaryResult:
        prompt = self._build_prompt(tweet)
        response = self._post_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You analyze X posts for a Chinese-speaking reader. "
                        "Return compact JSON with keys: title, translation, body, tags. "
                        "title should be at most 24 Chinese characters. "
                        "translation should be a complete faithful natural Chinese translation of the original post text, preserving the original meaning as closely as possible and not omitting any visible sentence. "
                        "body should be 2 to 5 concise Chinese sentences merged into one paragraph. "
                        "Do not simply restate the post. "
                        "If the post contains non-obvious investment logic, technical terms, market jargon, product names, policy concepts, or chain-of-thought that needs unpacking, explain the key concept and why it matters. "
                        "If the post is already simple and obvious, keep the commentary brief and do not over-explain. "
                        "Prioritize extracting stock ideas, sector ideas, recommendation logic, the author's likely motivation for mentioning it now, and what an investor should pay attention to next. "
                        "If quote-tweet or reply context is provided, use it in the commentary section instead of ignoring it. "
                        "If no stock idea is present, summarize the market view and potential implication instead. "
                        "tags should contain 1 to 3 short tags. "
                        f"Additional style requirement: {self.style_prompt}"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            timeout=90.0,
        )
        response.raise_for_status()

        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()
        parsed = self._parse_response(content)
        tags = parsed.get("tags", [])
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]

        return SummaryResult(
            title=str(parsed.get("title", "Post Summary")).strip() or "Post Summary",
            body=str(parsed.get("body", tweet.text)).strip() or tweet.text,
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
            translation=str(parsed.get("translation", "")).strip() or None,
        )

    def summarize_digest(self, username: str, tweets: list[Tweet], window: DigestWindow) -> SummaryResult:
        if not tweets:
            raise ValueError("summarize_digest requires at least one tweet")

        response = self._post_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize overnight X posts for a Chinese-speaking investment reader. "
                        "Return compact JSON with keys: title, body, tags. "
                        "title should be at most 24 Chinese characters. "
                        "body should be 3 to 6 concise sentences merged into one paragraph. "
                        "Prioritize extracting recommended stocks, sectors, investment themes, supporting reasons, "
                        "and why the author appears to be mentioning them now. "
                        "Do not just compress the posts; explain the deeper common thread if one exists. "
                        "If no direct recommendation exists, summarize the market view and likely watchlist implication. "
                        "tags should contain 1 to 3 short tags. "
                        f"Additional style requirement: {self.style_prompt}"
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_digest_prompt(username, tweets, window),
                },
            ],
            timeout=120.0,
        )
        response.raise_for_status()

        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()
        parsed = self._parse_response(content)
        tags = parsed.get("tags", [])
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]

        return SummaryResult(
            title=str(parsed.get("title", "Morning Digest")).strip() or "Morning Digest",
            body=str(parsed.get("body", "")).strip()
            or f"Collected {window.tweet_count} overnight posts from @{username}.",
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        )

    def _build_prompt(self, tweet: Tweet) -> str:
        author_label = tweet.display_name or tweet.username
        reply_context = ""
        if tweet.replying_to:
            reply_context = f"Replying to: {', '.join(f'@{name}' for name in tweet.replying_to)}\n"
        quoted_context = ""
        if tweet.quoted_text:
            quoted_author = tweet.quoted_display_name or tweet.quoted_username or "unknown"
            quoted_handle = f" (@{tweet.quoted_username})" if tweet.quoted_username else ""
            quoted_context = (
                f"Quoted post author: {quoted_author}{quoted_handle}\n"
                f"Quoted post content:\n{tweet.quoted_text}\n"
            )
        return (
            "Please analyze this X post in Chinese.\n\n"
            f"Author display name: {author_label}\n"
            f"Author username: @{tweet.username}\n"
            f"Published at: {tweet.published_at}\n"
            f"URL: {tweet.url}\n"
            f"{reply_context}"
            f"{quoted_context}"
            f"Content:\n{tweet.text}\n\n"
            "Output JSON only."
        )

    def _build_digest_prompt(self, username: str, tweets: list[Tweet], window: DigestWindow) -> str:
        lines = []
        for index, tweet in enumerate(tweets, start=1):
            lines.append(
                f"{index}. Time: {tweet.published_at}\n"
                f"URL: {tweet.url}\n"
                f"Content: {tweet.text}"
            )

        items = "\n\n".join(lines)
        return (
            "Please summarize these X posts in Chinese as one morning digest.\n\n"
            f"Author: @{username}\n"
            f"Window: {window.start_label} to {window.end_label}\n"
            f"Post count: {window.tweet_count}\n\n"
            f"Posts:\n{items}\n\n"
            "Output JSON only."
        )

    def _parse_response(self, content: str) -> dict[str, object]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError(f"DeepSeek response is not valid JSON: {content}")
            return json.loads(content[start : end + 1])

    def _post_chat_completion(self, messages: list[dict[str, str]], timeout: float) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                return httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "response_format": {"type": "json_object"},
                        "messages": messages,
                        "temperature": 0.3,
                        "stream": False,
                    },
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("DeepSeek request timed out on attempt %d/3", attempt)
                if attempt < 3:
                    time.sleep(attempt * 2)
        if last_exc is None:
            raise RuntimeError("DeepSeek request failed without an exception")
        raise last_exc
