from __future__ import annotations

import logging
import time

from .ai.deepseek import DeepSeekSummarizer
from .config import RuntimeConfigProvider, RuntimeSettings, StaticSettings
from .fetchers.x_scraper import XTimelineScraper
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

        logger.info("Starting fetch cycle for %d account(s)", len(runtime.x_usernames))
        scraper = XTimelineScraper(
            storage_state_path=self.static_settings.x_login_state_path,
            headless=self.static_settings.x_headless,
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
            logger.info("Fetching latest posts for @%s", username)
            tweets = scraper.fetch_latest(username=username, limit=runtime.x_fetch_limit)
            new_tweets = [tweet for tweet in tweets if not self.storage.has_tweet(tweet.tweet_id)]

            if not new_tweets:
                logger.info("No new posts found for @%s", username)
                continue

            logger.info("Found %d new post(s) for @%s", len(new_tweets), username)
            for tweet in new_tweets:
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
