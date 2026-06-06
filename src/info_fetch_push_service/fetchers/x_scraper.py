from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ..models import Tweet


class XTimelineScraper:
    def __init__(
        self,
        storage_state_path: Path,
        headless: bool = True,
        browser_channel: str | None = None,
        system_user_data_path: Path | None = None,
        imported_profile_path: Path | None = None,
    ) -> None:
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.browser_channel = browser_channel
        self.system_user_data_path = system_user_data_path
        self.imported_profile_path = imported_profile_path

    def login(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False, channel=self.browser_channel)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")

            print("A browser window has been opened for X login.")
            print("Complete the login flow in the browser.")
            print("Do not close the browser window yourself.")
            print("The session will be saved automatically after X login cookies are detected.")

            while True:
                cookies = {cookie["name"] for cookie in context.cookies("https://x.com")}
                if {"auth_token", "ct0"}.issubset(cookies):
                    break
                time.sleep(1)

            context.storage_state(path=str(self.storage_state_path))
            browser.close()

    def import_edge_login_state(self) -> int:
        local_app_data = Path(os.environ["LOCALAPPDATA"])
        src_root = local_app_data / "Microsoft" / "Edge" / "User Data"
        src_local_state = src_root / "Local State"
        src_default_profile = src_root / "Default"
        if not src_local_state.exists() or not src_default_profile.exists():
            raise RuntimeError("Could not locate the Microsoft Edge profile or Local State file.")

        try:
            self._export_storage_state_from_profile(src_root)
        except Exception as exc:
            raise RuntimeError(
                "Could not import the session from Microsoft Edge. "
                "Please close all Edge windows first, then run the import command again."
            ) from exc
        state = json.loads(self.storage_state_path.read_text(encoding="utf-8"))
        cookies = [cookie for cookie in state.get("cookies", []) if self._is_supported_domain(cookie.get("domain", ""))]
        if not cookies:
            raise RuntimeError(
                "The imported Edge session did not include any X cookies. "
                "Make sure you are logged into x.com in Edge before importing."
            )
        return len(cookies)

    def fetch_latest(self, username: str, limit: int) -> list[Tweet]:
        if not self.storage_state_path.exists() and not self._has_imported_profile() and not self._has_system_profile():
            raise FileNotFoundError(
                f"X login state file does not exist: {self.storage_state_path}. "
                "Run the login or import-edge-session command first."
            )

        if self.storage_state_path.exists():
            return self._fetch_with_storage_state(username, limit)

        if self._has_imported_profile():
            return self._fetch_with_profile_root(self.imported_profile_path, username, limit)

        if self._has_system_profile():
            return self._fetch_with_profile_root(self.system_user_data_path, username, limit)

        raise FileNotFoundError(
            f"X login state file does not exist: {self.storage_state_path}. "
            "Run the login or import-edge-session command first."
        )

    def _fetch_with_storage_state(self, username: str, limit: int) -> list[Tweet]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless, channel=self.browser_channel)
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
                      const userNameNode = article.querySelector('[data-testid="User-Name"]');
                      const displayName = userNameNode
                        ? [...userNameNode.querySelectorAll('span')]
                            .map((node) => (node.innerText || '').trim())
                            .find((value) => value && !value.startsWith('@'))
                        : '';
                      const tweetIdMatch = statusLink ? statusLink.match(/\\/status\\/(\\d+)/) : null;

                      return {
                        statusLink,
                        text: textNode ? textNode.innerText : '',
                        publishedAt: timeNode ? timeNode.getAttribute('datetime') : '',
                        displayName,
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
                    display_name = (raw_tweet.get("displayName", "") or "").strip() or None

                    if not status_link or not tweet_id or not text:
                        continue

                    tweets[tweet_id] = Tweet(
                        tweet_id=tweet_id,
                        username=username,
                        display_name=display_name,
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

            # Return newest posts first. X renders newest-first on the page,
            # but we sort explicitly so mixed DOM order or extra scrolling
            # cannot accidentally surface older items as the "latest" ones.
            ordered = sorted(
                tweets.values(),
                key=lambda item: (item.published_at, item.tweet_id),
                reverse=True,
            )[:limit]
            self._enrich_tweets(context, ordered)
            browser.close()
            return ordered

    def _fetch_with_profile_root(self, profile_root: Path | None, username: str, limit: int) -> list[Tweet]:
        if profile_root is None:
            raise RuntimeError("Profile root path is not configured.")
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_root),
                channel=self.browser_channel or "msedge",
                headless=self.headless,
            )
            page = context.new_page()
            page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
            except PlaywrightTimeoutError as exc:
                context.close()
                raise RuntimeError(f"Could not load timeline for @{username} from the Edge profile.") from exc

            tweets = self._collect_tweets(page=page, username=username, limit=limit)
            ordered = sorted(
                tweets.values(),
                key=lambda item: (item.published_at, item.tweet_id),
                reverse=True,
            )[:limit]
            self._enrich_tweets(context, ordered)
            context.close()
            return ordered

    def _collect_tweets(self, page, username: str, limit: int) -> dict[str, Tweet]:
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
                  const userNameNode = article.querySelector('[data-testid="User-Name"]');
                  const displayName = userNameNode
                    ? [...userNameNode.querySelectorAll('span')]
                        .map((node) => (node.innerText || '').trim())
                        .find((value) => value && !value.startsWith('@'))
                    : '';
                  const tweetIdMatch = statusLink ? statusLink.match(/\\/status\\/(\\d+)/) : null;

                  return {
                    statusLink,
                    text: textNode ? textNode.innerText : '',
                    publishedAt: timeNode ? timeNode.getAttribute('datetime') : '',
                    displayName,
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
                display_name = (raw_tweet.get("displayName", "") or "").strip() or None

                if not status_link or not tweet_id or not text:
                    continue

                tweets[tweet_id] = Tweet(
                    tweet_id=tweet_id,
                    username=username,
                    display_name=display_name,
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

        return tweets

    def _enrich_tweets(self, context, tweets: list[Tweet]) -> None:
        if not tweets:
            return

        page = context.new_page()
        try:
            for tweet in tweets:
                page.goto(tweet.url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
                except PlaywrightTimeoutError:
                    continue

                self._expand_long_post(page)

                detail = page.eval_on_selector(
                    'article[data-testid="tweet"]',
                    """
                    (article, username) => {
                      const normalize = (value) => (value || '').trim();
                      const userBlocks = [...article.querySelectorAll('[data-testid="User-Name"]')].map((block) => {
                        const pieces = [...block.querySelectorAll('span')]
                          .map((node) => normalize(node.innerText))
                          .filter(Boolean);
                        const handle = pieces.find((value) => value.startsWith('@')) || '';
                        const name = pieces.find((value) => !value.startsWith('@')) || '';
                        return { name, handle };
                      }).filter((item) => item.name || item.handle);
                      const textBlocks = [...article.querySelectorAll('[data-testid="tweetText"]')]
                        .map((node) => normalize(node.innerText))
                        .filter(Boolean);
                      const articleText = normalize(article.innerText);
                      const quotedAuthor = userBlocks.length > 1 ? userBlocks[1] : null;
                      const anchorHandles = [...new Set(
                        [...article.querySelectorAll('a[href^="/"]')]
                          .map((node) => normalize(node.innerText))
                          .filter((value) => value.startsWith('@'))
                      )];
                      const hasReplyContext = /replying to|in reply to|\\u56de\\u590d|\\u56de\\u8986|\\ub2f5\\uae00|\\u8fd4\\u4fe1\\u5148|en r\\u00e9ponse|respondiendo a|em resposta|antwort an/i.test(articleText);
                      const replyTargets = hasReplyContext
                        ? anchorHandles.filter((handle) => {
                            const normalizedHandle = handle.toLowerCase();
                            const selfHandle = `@${String(username || '').toLowerCase()}`;
                            const quotedHandle = quotedAuthor && quotedAuthor.handle
                              ? quotedAuthor.handle.toLowerCase()
                              : '';
                            return normalizedHandle !== selfHandle && normalizedHandle !== quotedHandle;
                          }).slice(0, 5)
                        : [];

                      return {
                        displayName: userBlocks[0] ? userBlocks[0].name : '',
                        mainText: textBlocks[0] || '',
                        quotedText: textBlocks.length > 1 ? textBlocks.slice(1).join('\\n\\n') : '',
                        quotedDisplayName: quotedAuthor ? quotedAuthor.name : '',
                        quotedUsername: quotedAuthor && quotedAuthor.handle
                          ? quotedAuthor.handle.replace(/^@/, '')
                          : '',
                        replyingTo: replyTargets,
                      };
                    }
                    """,
                    tweet.username,
                )

                if not detail:
                    continue

                main_text = (detail.get("mainText", "") or "").strip()
                if main_text:
                    tweet.text = main_text

                display_name = (detail.get("displayName", "") or "").strip()
                if display_name:
                    tweet.display_name = display_name

                reply_targets = [
                    str(value).strip().lstrip("@")
                    for value in detail.get("replyingTo", []) or []
                    if str(value).strip()
                ]
                tweet.replying_to = reply_targets or None

                quoted_username = (detail.get("quotedUsername", "") or "").strip().lstrip("@")
                quoted_display_name = (detail.get("quotedDisplayName", "") or "").strip()
                quoted_text = (detail.get("quotedText", "") or "").strip()
                tweet.quoted_username = quoted_username or None
                tweet.quoted_display_name = quoted_display_name or None
                tweet.quoted_text = quoted_text or None
        finally:
            page.close()

    def _expand_long_post(self, page) -> None:
        try:
            page.evaluate(
                """
                () => {
                  const labels = ['Show more', 'Read more', '显示更多', '展开', '更多'];
                  const nodes = [...document.querySelectorAll('button, div[role="button"], span, a')];
                  for (const node of nodes) {
                    const text = (node.innerText || '').trim();
                    if (!labels.includes(text)) {
                      continue;
                    }
                    const clickable = node.closest('button, a, div[role="button"]') || node;
                    if (clickable instanceof HTMLElement) {
                      clickable.click();
                      return true;
                    }
                  }
                  return false;
                }
                """
            )
            page.wait_for_timeout(200)
        except Exception:
            return

    def _export_storage_state_from_profile(self, profile_root: Path) -> None:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_root),
                channel=self.browser_channel or "msedge",
                headless=True,
            )
            page = context.new_page()
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            context.storage_state(path=str(self.storage_state_path))
            context.close()

    def _has_imported_profile(self) -> bool:
        if self.imported_profile_path is None:
            return False
        return (self.imported_profile_path / "Default").exists() and (self.imported_profile_path / "Local State").exists()

    def _has_system_profile(self) -> bool:
        if self.system_user_data_path is None:
            return False
        return (self.system_user_data_path / "Default").exists() and (self.system_user_data_path / "Local State").exists()

    def _is_supported_domain(self, domain: str) -> bool:
        normalized = domain.lower()
        return "x.com" in normalized or "twitter.com" in normalized
