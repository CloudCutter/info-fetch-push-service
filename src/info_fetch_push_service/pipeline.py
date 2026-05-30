from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dt_time

from .ai.deepseek import DeepSeekSummarizer
from .config import RuntimeConfigProvider, RuntimeSettings, StaticSettings
from .fetchers.x_scraper import XTimelineScraper
from .models import DigestWindow, SummaryResult, Tweet
from .notifiers.feishu import FeishuNotifier
from .storage import Storage

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, static_settings: StaticSettings, runtime_config_provider: RuntimeConfigProvider) -> None:
        self.static_settings = static_settings
        self.runtime_config_provider = runtime_config_provider
        self.storage = Storage(static_settings.database_path)

    def close(self) -> None:
        self.storage.close()

    def run_once(self, runtime_settings: RuntimeSettings | None = None) -> None:
        runtime = runtime_settings or self.runtime_config_provider.load()
        if not runtime.service_enabled:
            logger.info("Service is disabled in runtime config, skipping this cycle")
            return

        now_local = datetime.now(self.static_settings.local_timezone)
        if self._is_within_quiet_hours(runtime, now_local):
            logger.info(
                "Current local time %s is within quiet hours %02d:00-%02d:00, skipping fetch",
                now_local.isoformat(timespec="seconds"),
                runtime.quiet_hours_start_hour,
                runtime.quiet_hours_end_hour,
            )
            return

        logger.info("Starting fetch cycle for %d account(s)", len(runtime.x_usernames))
        scraper = XTimelineScraper(
            storage_state_path=self.static_settings.x_login_state_path,
            headless=self.static_settings.x_headless,
            browser_channel=self.static_settings.x_browser_channel,
            system_user_data_path=self.static_settings.x_system_user_data_path,
            imported_profile_path=self.static_settings.x_imported_profile_path,
        )
        summarizer = DeepSeekSummarizer(
            api_key=self.static_settings.deepseek_api_key,
            base_url=self.static_settings.deepseek_base_url,
            model=runtime.deepseek_model,
            style_prompt=runtime.summary_style_prompt,
        )
        notifier = FeishuNotifier(
            webhook_url=self.static_settings.feishu_webhook_url,
            secret=self.static_settings.feishu_bot_secret,
            mention_all=runtime.feishu_mention_all,
        )

        for username in runtime.x_usernames:
            limit = max(runtime.x_fetch_limit, runtime.morning_digest_fetch_limit)
            logger.info("Fetching latest posts for @%s", username)
            tweets = scraper.fetch_latest(username=username, limit=limit)
            new_tweets = [tweet for tweet in tweets if not self.storage.has_tweet(tweet.tweet_id)]

            if not new_tweets:
                logger.info("No new posts found for @%s", username)
                continue

            logger.info("Found %d new post(s) for @%s", len(new_tweets), username)
            digest_candidates, regular_tweets = self._split_digest_candidates(runtime, now_local, username, new_tweets)

            if digest_candidates:
                self._process_morning_digest(
                    notifier=notifier,
                    summarizer=summarizer,
                    username=username,
                    tweets=digest_candidates,
                    now_local=now_local,
                    runtime=runtime,
                )

            # We fetch more posts than the regular push limit so morning digests can
            # sweep the full quiet-hours window. Outside that digest path, only the
            # newest x_fetch_limit posts should be sent individually to avoid a large
            # historical backfill flood on a fresh run.
            regular_tweets = sorted(
                regular_tweets,
                key=lambda item: self._parse_published_at(item.published_at),
                reverse=True,
            )[: runtime.x_fetch_limit]

            for tweet in regular_tweets:
                logger.info("Summarizing tweet %s", tweet.tweet_id)
                summary = summarizer.summarize(tweet)
                logger.info("Sending Feishu notification for tweet %s", tweet.tweet_id)
                notifier.send_tweet_summary(tweet, summary)
                self.storage.save_tweet(tweet, summary)

    def serve_forever(self) -> None:
        while True:
            cycle_started_at = time.time()
            sleep_seconds = 60
            try:
                runtime = self.runtime_config_provider.load()
                self.run_once(runtime)
                sleep_seconds = runtime.x_poll_interval_seconds
            except Exception:
                logger.exception("Fetch cycle failed")
                try:
                    runtime = self.runtime_config_provider.load()
                    sleep_seconds = runtime.x_poll_interval_seconds
                except Exception:
                    logger.exception("Could not reload runtime config after failure")

            elapsed = time.time() - cycle_started_at
            sleep_seconds = max(0, sleep_seconds - int(elapsed))
            logger.info("Sleeping for %d seconds", sleep_seconds)
            time.sleep(sleep_seconds)

    def _process_morning_digest(
        self,
        notifier: FeishuNotifier,
        summarizer: DeepSeekSummarizer,
        username: str,
        tweets: list[Tweet],
        now_local: datetime,
        runtime: RuntimeSettings,
    ) -> None:
        digest_date = now_local.date()
        window = DigestWindow(
            start_label=f"{digest_date.isoformat()} {runtime.quiet_hours_start_hour:02d}:00",
            end_label=f"{digest_date.isoformat()} {runtime.quiet_hours_end_hour:02d}:00",
            tweet_count=len(tweets),
        )
        logger.info("Summarizing morning digest for @%s with %d post(s)", username, len(tweets))
        summary = summarizer.summarize_digest(username=username, tweets=tweets, window=window)
        logger.info("Sending morning digest for @%s", username)
        notifier.send_digest_summary(username=username, summary=summary, tweets=tweets, window=window)
        digest_marker = SummaryResult(
            title=f"{summary.title} [digest]",
            body=summary.body,
            tags=summary.tags,
        )
        for tweet in tweets:
            self.storage.save_tweet(tweet, digest_marker)
        self.storage.set_state(self._digest_state_key(username, digest_date), "sent")

    def _split_digest_candidates(
        self,
        runtime: RuntimeSettings,
        now_local: datetime,
        username: str,
        new_tweets: list[Tweet],
    ) -> tuple[list[Tweet], list[Tweet]]:
        if not runtime.quiet_hours_enabled or now_local.hour < runtime.quiet_hours_end_hour:
            return [], new_tweets

        digest_date = now_local.date()
        if self.storage.get_state(self._digest_state_key(username, digest_date)) == "sent":
            return [], new_tweets

        digest_start = datetime.combine(
            digest_date,
            dt_time(hour=runtime.quiet_hours_start_hour),
            tzinfo=self.static_settings.local_timezone,
        )
        digest_end = datetime.combine(
            digest_date,
            dt_time(hour=runtime.quiet_hours_end_hour),
            tzinfo=self.static_settings.local_timezone,
        )

        digest_candidates: list[Tweet] = []
        regular_tweets: list[Tweet] = []
        for tweet in new_tweets:
            published_local = self._parse_published_at(tweet.published_at)
            if digest_start <= published_local < digest_end:
                digest_candidates.append(tweet)
            else:
                regular_tweets.append(tweet)

        digest_candidates.sort(key=lambda item: self._parse_published_at(item.published_at))
        regular_tweets.sort(key=lambda item: self._parse_published_at(item.published_at))
        return digest_candidates, regular_tweets

    def _is_within_quiet_hours(self, runtime: RuntimeSettings, now_local: datetime) -> bool:
        if not runtime.quiet_hours_enabled:
            return False
        current_hour = now_local.hour
        return runtime.quiet_hours_start_hour <= current_hour < runtime.quiet_hours_end_hour

    def _parse_published_at(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(self.static_settings.local_timezone)

    def _digest_state_key(self, username: str, digest_date: date) -> str:
        return f"morning_digest_sent:{username}:{digest_date.isoformat()}"
