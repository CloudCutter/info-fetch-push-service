from __future__ import annotations

import json

import httpx

from ..models import DigestWindow, SummaryResult, Tweet


class DeepSeekSummarizer:
    def __init__(self, api_key: str, base_url: str, model: str, style_prompt: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.style_prompt = style_prompt

    def summarize(self, tweet: Tweet) -> SummaryResult:
        prompt = self._build_prompt(tweet)
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You summarize X posts for a Chinese-speaking reader. "
                            "Return compact JSON with keys: title, body, tags. "
                            "title should be at most 24 Chinese characters. "
                            "body should be 2 to 4 concise sentences merged into one paragraph. "
                            "Prioritize extracting stock ideas, sector ideas, recommendation logic, and the author's likely motivation for mentioning it now. "
                            "If no stock idea is present, summarize the market view and potential implication instead. "
                            "tags should contain 1 to 3 short tags. "
                            f"Additional style requirement: {self.style_prompt}"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "stream": False,
            },
            timeout=60.0,
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
        )

    def summarize_digest(self, username: str, tweets: list[Tweet], window: DigestWindow) -> SummaryResult:
        if not tweets:
            raise ValueError("summarize_digest requires at least one tweet")

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You summarize overnight X posts for a Chinese-speaking investment reader. "
                            "Return compact JSON with keys: title, body, tags. "
                            "title should be at most 24 Chinese characters. "
                            "body should be 3 to 5 concise sentences merged into one paragraph. "
                            "Prioritize extracting recommended stocks, sectors, investment themes, supporting reasons, "
                            "and why the author appears to be mentioning them now. "
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
                "temperature": 0.3,
                "stream": False,
            },
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
            title=str(parsed.get("title", "Morning Digest")).strip() or "Morning Digest",
            body=str(parsed.get("body", "")).strip()
            or f"Collected {window.tweet_count} overnight posts from @{username}.",
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
        )

    def _build_prompt(self, tweet: Tweet) -> str:
        return (
            "Please summarize this X post in Chinese.\n\n"
            f"Author: @{tweet.username}\n"
            f"Published at: {tweet.published_at}\n"
            f"URL: {tweet.url}\n"
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
