from __future__ import annotations

from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models import Tweet


class XTimelineScraper:
    def __init__(self, storage_state_path: Path, headless: bool = True) -> None:
        self.storage_state_path = storage_state_path
        self.headless = headless

    def login(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")

            print("A browser window has been opened for X login.")
            print("Complete the login in the browser, then press Enter here to save the session.")
            input()

            context.storage_state(path=str(self.storage_state_path))
            browser.close()

    def fetch_latest(self, username: str, limit: int) -> list[Tweet]:
        if not self.storage_state_path.exists():
            raise FileNotFoundError(
                f"X login state file does not exist: {self.storage_state_path}. Run the login command first."
            )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            context = browser.new_context(storage_state=str(self.storage_state_path))
            page = context.new_page()
            page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
            except PlaywrightTimeoutError as exc:
                browser.close()
                raise RuntimeError(f"Could not load timeline for @{username}. X may require re-login.") from exc

            tweets: dict[str, Tweet] = {}
            scroll_attempts = 0

            while len(tweets) < limit and scroll_attempts < 4:
                for raw_tweet in page.eval_on_selector_all(
                    'article[data-testid="tweet"]',
                    """
                    (articles, username) => articles.map((article) => {
                      const statusLink = [...article.querySelectorAll('a[href*="/status/"]')]
                        .map((anchor) => anchor.getAttribute('href'))
                        .find((href) => href && href.startsWith(`/${username}/status/`));
                      const textNode = article.querySelector('[data-testid="tweetText"]');
                      const timeNode = article.querySelector('time');
                      const tweetIdMatch = statusLink ? statusLink.match(/\\/status\\/(\\d+)/) : null;

                      return {
                        statusLink,
                        text: textNode ? textNode.innerText : '',
                        publishedAt: timeNode ? timeNode.getAttribute('datetime') : '',
                        tweetId: tweetIdMatch ? tweetIdMatch[1] : '',
                      };
                    })
                    """,
                    username,
                ):
                    status_link = raw_tweet.get("statusLink", "")
                    tweet_id = raw_tweet.get("tweetId", "")
                    text = (raw_tweet.get("text", "") or "").strip()
                    published_at = raw_tweet.get("publishedAt", "") or ""

                    if not status_link or not tweet_id or not text:
                        continue

                    tweets[tweet_id] = Tweet(
                        tweet_id=tweet_id,
                        username=username,
                        text=text,
                        url=f"https://x.com{status_link}",
                        published_at=published_at,
                    )

                    if len(tweets) >= limit:
                        break

                if len(tweets) >= limit:
                    break

                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(1500)
                scroll_attempts += 1

            browser.close()
            ordered = sorted(tweets.values(), key=lambda item: (item.published_at, item.tweet_id))
            return ordered[:limit]
