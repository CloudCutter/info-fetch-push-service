# X Info Fetch Push Service

## Product Overview

This project runs locally, monitors selected X accounts, detects newly published posts, summarizes only the new items with DeepSeek, and pushes the results to a Feishu bot webhook.

The product goal is:

- avoid the paid X official API
- avoid repeated summaries for old posts
- keep deployment simple enough for a personal machine
- allow runtime config changes without restarting the whole service
- support quiet hours and a morning digest

## How It Works

```text
Normal hours:
  Scheduler
    -> X Scraper
    -> Compare latest posts with locally stored processed tweet ids
    -> If no new posts: stop here and do not call DeepSeek
    -> If new posts exist: call DeepSeek for summary
    -> Push result to Feishu
    -> Save processed tweet ids and summaries into SQLite

Quiet hours:
  01:00-08:00 local time
    -> no fetch
    -> no DeepSeek call

After 08:00:
  first cycle of the day
    -> fetch overnight posts from the quiet window
    -> summarize them as one digest
    -> send one Feishu digest message
    -> mark those posts as processed
```

## Current Architecture

```text
src/info_fetch_push_service/
  ai/deepseek.py              DeepSeek summary client
  fetchers/x_scraper.py       X page scraper based on Playwright
  notifiers/feishu.py         Feishu webhook sender
  config.py                   Static config and runtime config loader
  storage.py                  SQLite persistence and pipeline state
  pipeline.py                 Main fetch/summarize/push workflow
  main.py                     CLI entrypoint

config/runtime.example.json   Runtime config template
config/runtime.json           Local runtime config, loaded every cycle
data/service.db               Local SQLite database
data/x-login-state.json       Saved X login session
```

## Config Design

The project uses two layers of config.

### 1. Static Config

Static config is read from `.env`. These values are environment-level settings and normally require restart after modification.

Fields:

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`
- `X_BROWSER_CHANNEL`
- `X_HEADLESS`
- `LOCAL_TIMEZONE`
- `X_LOGIN_STATE_PATH`
- `DATABASE_PATH`
- `RUNTIME_CONFIG_PATH`

### 2. Runtime Config

Runtime config is stored in `config/runtime.json`. It is reloaded before every cycle, so changes take effect in the next polling round.

Fields:

- `service_enabled`
- `x_usernames`
- `x_poll_interval_seconds`
- `x_fetch_limit`
- `quiet_hours_enabled`
- `quiet_hours_start_hour`
- `quiet_hours_end_hour`
- `morning_digest_fetch_limit`
- `deepseek_model`
- `summary_style_prompt`
- `feishu_mention_all`

## Current Runtime Config Template

```json
{
  "service_enabled": true,
  "x_usernames": ["NullOreo_"],
  "x_poll_interval_seconds": 300,
  "x_fetch_limit": 5,
  "quiet_hours_enabled": true,
  "quiet_hours_start_hour": 1,
  "quiet_hours_end_hour": 8,
  "morning_digest_fetch_limit": 20,
  "deepseek_model": "deepseek-v4-flash",
  "summary_style_prompt": "Write the summary in Chinese for an investment-focused reader. First determine whether the post explicitly or implicitly recommends a stock, ETF, sector, or investment theme. If yes, identify the target, summarize the recommendation reason, and infer why the author is recommending it now. If no direct stock is mentioned, summarize the market view, sector implication, and possible watchlist direction. Return one short title and 2 to 4 high-signal sentences.",
  "feishu_mention_all": false
}
```

## Product Behavior Rules

- If the latest fetched posts are already present in local storage, DeepSeek must not be called.
- Only newly discovered tweet ids should enter the summary stage.
- From `01:00` to `08:00` local time, the service must not fetch X and must not call DeepSeek.
- After `08:00` local time, the first cycle should summarize overnight posts from the quiet window into one digest.
- Processed tweet ids and summaries are stored in SQLite to prevent repeat pushes.
- Runtime config changes should take effect in the next polling cycle.

## Local Setup

### 1. Create the virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -e .
python -m playwright install chromium
```

### 3. Create `.env`

Use `.env.example` as the base:

```powershell
Copy-Item .env.example .env
```

Then fill at least:

- `DEEPSEEK_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET` if your Feishu bot requires signing

### 4. Initialize runtime config

```powershell
.venv\Scripts\python -m info_fetch_push_service.main init-runtime-config
```

### 5. Login to X

```powershell
.venv\Scripts\python -m info_fetch_push_service.main login
```

This opens a browser window. Complete X login manually. After X redirects to the home timeline, the session will be saved to `data/x-login-state.json` automatically.

`X_BROWSER_CHANNEL` defaults to `msedge`, so both login and scraping use your local Microsoft Edge installation.

### Alternative: import the existing Edge session

If X blocks the automation login flow because it treats it as a new device, close all Microsoft Edge windows first and then run:

```powershell
.venv\Scripts\python -m info_fetch_push_service.main import-edge-session
```

This imports X-related cookies from your existing Edge profile into `data/x-login-state.json`.

### 6. Run one test cycle

```powershell
.venv\Scripts\python -m info_fetch_push_service.main run-once
```

### 7. Run as a local service

```powershell
.venv\Scripts\python -m info_fetch_push_service.main serve
```

## Daily Usage

### Change the monitored X accounts

Edit `config/runtime.json`:

```json
"x_usernames": ["NullOreo_", "hanking66"]
```

The next cycle will use the new list automatically.

### Change the polling frequency

Edit:

```json
"x_poll_interval_seconds": 300
```

`300` means 5 minutes.

### Change the summary style

Edit:

```json
"summary_style_prompt": "Write the summary in Chinese for an investment-focused reader. First determine whether the post explicitly or implicitly recommends a stock, ETF, sector, or investment theme. If yes, identify the target, summarize the recommendation reason, and infer why the author is recommending it now. If no direct stock is mentioned, summarize the market view, sector implication, and possible watchlist direction. Return one short title and 2 to 4 high-signal sentences."
```

### Configure quiet hours and morning digest

Edit:

```json
"quiet_hours_enabled": true,
"quiet_hours_start_hour": 1,
"quiet_hours_end_hour": 8,
"morning_digest_fetch_limit": 20
```

Behavior:

- from `01:00` to `07:59`, the service does not fetch X and does not call DeepSeek
- after `08:00`, the first cycle of the day collects posts published during `01:00-08:00`
- those overnight posts are summarized into one digest message
- tweets published after `08:00` continue to be processed normally as individual updates

If an account posts heavily, increase `morning_digest_fetch_limit` so the overnight window is fully covered.

### Temporarily pause the service

Edit:

```json
"service_enabled": false
```

The next cycle will skip all work.

## Storage Logic

SQLite stores processed tweet records and pipeline state. The current logic prevents repeated API calls like this:

1. Fetch latest posts from X
2. Check each fetched `tweet_id` against SQLite
3. Keep only unseen posts
4. If unseen post count is `0`, skip DeepSeek completely
5. If unseen posts fall inside the overnight quiet window, summarize them into one morning digest
6. Otherwise summarize them individually

This satisfies the rule that no DeepSeek request should be made when there are no new posts.

## Known Limitations

- X page structure may change and require scraper adjustment
- X login must be refreshed manually when expired
- The current push target is Feishu only
- Overnight coverage depends on `morning_digest_fetch_limit`; very high-volume accounts may require a higher value

## Troubleshooting

### 1. DeepSeek works but Feishu push fails

Check:

- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`
- whether the Feishu bot has IP or keyword restrictions enabled

### 2. X page opens but no tweets are found

Possible reasons:

- login expired
- X showed a challenge page
- the page structure changed
- automation login was treated as a new device

Retry:

```powershell
.venv\Scripts\python -m info_fetch_push_service.main login
```

Or, if you are already logged into X in Edge:

```powershell
.venv\Scripts\python -m info_fetch_push_service.main import-edge-session
```

### 3. Runtime config changes do not seem applied

Confirm that you edited `config/runtime.json`, not `config/runtime.example.json`.

## References

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Feishu Custom Bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)
