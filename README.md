# X Info Fetch Push Service

本项目会在本地抓取指定 X 账号的新推文，调用 DeepSeek API 生成中文摘要，并推送到飞书群机器人。

## 特点

- 不使用 X 官方 API
- 本地保存 X 登录态和已处理推文
- 运行时配置支持动态生效
- 通过 DeepSeek API 做摘要
- 通过飞书群机器人推送消息

## 架构

```text
Scheduler -> X Scraper -> Normalizer -> Deduper -> DeepSeek Summarizer -> Feishu Notifier
                                 |                                          |
                                 +---------------- SQLite ------------------+
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
```

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m playwright install chromium
Copy-Item .env.example .env
```

## 静态配置

静态配置放在 `.env`，主要是密钥、路径、Webhook 这类通常需要重启才生效的内容。

关键字段：

- `DEEPSEEK_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`
- `X_LOGIN_STATE_PATH`
- `DATABASE_PATH`
- `RUNTIME_CONFIG_PATH`
- `X_HEADLESS`

## 运行时配置

运行时配置放在 `config/runtime.json`，每轮执行前都会重新读取一次，因此修改后下一轮即可生效。

先初始化模板：

```powershell
info-fetch-push init-runtime-config
```

默认运行时配置文件内容如下：

```json
{
  "service_enabled": true,
  "x_usernames": ["OpenAI", "xai"],
  "x_poll_interval_seconds": 600,
  "x_fetch_limit": 5,
  "deepseek_model": "deepseek-v4-flash",
  "summary_style_prompt": "请输出适合通知消息阅读的中文摘要。先给出一句简短标题，再给出 2 到 4 句高信息密度摘要。如果内容偏观点表达，请提炼核心判断；如果内容偏新闻，请强调事件和影响。",
  "feishu_mention_all": false
}
```

动态生效的字段：

- `service_enabled`
- `x_usernames`
- `x_poll_interval_seconds`
- `x_fetch_limit`
- `deepseek_model`
- `summary_style_prompt`
- `feishu_mention_all`

## 首次登录 X

```powershell
info-fetch-push login
```

程序会打开浏览器。完成登录后，回终端按回车保存登录态。

## 查看当前运行时配置

```powershell
info-fetch-push show-config
```

## 运行

先执行一次：

```powershell
info-fetch-push run-once
```

常驻运行：

```powershell
info-fetch-push serve
```

## 注意事项

- X 页面结构可能变化，必要时需要调整抓取选择器
- 如果 X 登录失效，重新执行 `info-fetch-push login`
- 飞书自定义机器人用于群通知，最适合做消息推送
- DeepSeek 模型名和价格可能变动，建议优先参考官方文档

## 参考文档

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Feishu Custom Bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)
