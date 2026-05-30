# X 推文抓取与飞书推送服务

## 项目简介

这个项目运行在本地，用来监控指定 X 账号，抓取新推文，调用 DeepSeek 生成中文摘要，并推送到飞书机器人。

当前设计目标：

- 不使用 X 官方付费 API
- 已处理过的推文不再重复总结和推送
- 支持运行时动态修改监控账号和摘要风格
- 支持静默时段与早间汇总

## 工作流程

```text
正常时段：
  定时器
    -> 抓取 X 账号主页
    -> 和本地数据库中的 tweet_id 做比较
    -> 如果没有新推文：直接结束，不调用 DeepSeek
    -> 如果有新推文：调用 DeepSeek 摘要
    -> 推送到飞书
    -> 写入 SQLite，标记为已处理

静默时段：
  01:00-08:00（本地时区）
    -> 不抓取
    -> 不调用 DeepSeek

08:00 之后：
  当天第一次有效轮询
    -> 补抓 01:00-08:00 这段时间内的新推文
    -> 汇总成一条晨报
    -> 发到飞书
```

## 目录结构

```text
src/info_fetch_push_service/
  ai/deepseek.py
  fetchers/x_scraper.py
  notifiers/feishu.py
  config.py
  storage.py
  pipeline.py
  main.py

config/runtime.example.json
config/runtime.json
data/service.db
data/x-login-state.json
logs/service.log
```

## 配置说明

项目分成两层配置。

### 1. 静态配置

静态配置放在 `.env`，一般修改后需要重启服务。

字段：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`
- `X_BROWSER_CHANNEL`
- `X_HEADLESS`
- `LOCAL_TIMEZONE`
- `X_LOGIN_STATE_PATH`
- `X_SYSTEM_USER_DATA_PATH`
- `X_IMPORTED_PROFILE_PATH`
- `DATABASE_PATH`
- `RUNTIME_CONFIG_PATH`

### 2. 运行时配置

运行时配置放在 `config/runtime.json`，每轮执行前都会重新读取一次，修改后下一轮自动生效。

字段：

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

## 当前运行时配置模板

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

## 防重机制

当前防重逻辑是基于 `tweet_id` 做的。

实现方式：

1. 每次抓取后，程序会拿到若干条最新推文
2. 对每条推文读取它的 `tweet_id`
3. 到 SQLite 表 `processed_tweets` 里查询这个 `tweet_id` 是否已经存在
4. 如果已经存在，说明这条推文之前已经处理过，就不会再次调用 DeepSeek，也不会再次推送
5. 如果不存在，才会进入摘要和推送流程
6. 推送成功后，把这条推文写入 `processed_tweets`

对应代码：

- 防重查询：[storage.py](/E:/claudeProject/info-fetch-push-service/src/info_fetch_push_service/storage.py)
- 主流程判断：[pipeline.py](/E:/claudeProject/info-fetch-push-service/src/info_fetch_push_service/pipeline.py)

也就是说，当前的“去重键”就是：

- `tweet_id`

不是按文本去重，也不是按时间去重。

## 静默时段与早间汇总

当前规则：

- `01:00-08:00` 不抓取
- `08:00` 后第一轮，把夜间推文统一汇总

相关配置：

```json
"quiet_hours_enabled": true,
"quiet_hours_start_hour": 1,
"quiet_hours_end_hour": 8,
"morning_digest_fetch_limit": 20
```

说明：

- `morning_digest_fetch_limit` 表示早间汇总时最多向上补抓多少条
- 如果某个账号夜间发文特别多，需要把这个值调大

## 安装与运行

### 1. 创建虚拟环境

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 安装依赖

```powershell
pip install -e .
python -m playwright install chromium
```

### 3. 准备 `.env`

```powershell
Copy-Item .env.example .env
```

至少填写：

- `DEEPSEEK_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`（如果飞书机器人开启签名）

推荐同时确认：

- `X_BROWSER_CHANNEL=msedge`
- `X_SYSTEM_USER_DATA_PATH` 指向本机 Edge 用户数据目录

默认值一般就是：

```text
%LOCALAPPDATA%\Microsoft\Edge\User Data
```

### 4. 初始化运行时配置

```powershell
.venv\Scripts\python -m info_fetch_push_service.main init-runtime-config
```

### 5. 登录 X

```powershell
.venv\Scripts\python -m info_fetch_push_service.main login
```

### 6. 如果 X 阻止自动化登录，可导入现有 Edge 会话

```powershell
.venv\Scripts\python -m info_fetch_push_service.main import-edge-session
```

当前版本抓取最新推文时，会优先直接复用你本机 Edge 的真实登录资料。
这能比单独导出的会话文件更稳定地看到最新帖子。

注意：

- 抓取执行时，Edge 需要处于关闭状态
- 如果 Edge 正在运行，程序可能无法打开资料目录并会报错
- 这时先关闭所有 Edge 窗口，再重试 `run-once` 或 `serve`

### 7. 运行一次

```powershell
.venv\Scripts\python -m info_fetch_push_service.main run-once
```

### 8. 后台常驻运行

```powershell
.venv\Scripts\python -m info_fetch_push_service.main serve
```

### 9. 停止后台服务

```powershell
.venv\Scripts\python -m info_fetch_push_service.main stop
```

## 日志

主日志文件：

- `logs/service.log`

已开启日志轮转：

- 单文件约 `2 MB`
- 保留 `5` 份历史日志

如果你是用额外的 PowerShell 重定向方式启动，也可能看到：

- `logs/service.out.log`
- `logs/service.err.log`

## 当前状态

最新抓取问题已经修复。

程序现在会优先复用你本机 Edge 的真实登录资料，而不是只依赖单独导出的 `x-login-state.json`。
这样可以抓到你在浏览器里实际能看到的最新推文。

例如，`@NullOreo_` 的最新抓取结果已经能看到这条帖子：

- `https://x.com/NullOreo_/status/2060090619897479621`

也就是说，之前抓到 `2025` 年旧推文的问题，已经不是当前版本的行为。

当前最需要注意的限制是：

- 抓取时不要让 Edge 保持打开
- 如果 Edge 正在运行，最新抓取可能失败
- 失败时程序会明确报错，而不会静默退回旧会话

## 结论

当前这套逻辑的核心是：

- `tweet_id` 去重，保证已处理推文不会重复调用 DeepSeek 和重复推送
- 优先使用真实 Edge 登录资料，保证尽可能抓到浏览器里可见的最新推文

## 参考文档

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Feishu Custom Bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)
