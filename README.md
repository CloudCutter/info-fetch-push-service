# X 推文抓取与飞书推送服务

## 项目简介

这个项目运行在本地或服务器上，用来监控指定 X 账号，抓取新推文，调用 DeepSeek 生成中文翻译与点评，并推送到飞书机器人。

当前设计目标：

- 不使用 X 官方付费 API
- 已处理过的推文不再重复总结和推送
- 支持运行时动态修改监控账号和摘要风格
- 支持静默时段与早间汇总
- 同时兼容本机 Windows 运行和 Linux 服务器部署

## 当前工作流

```text
正常时段：
  定时器
    -> 抓取 X 账号主页
    -> 对新推文补抓详情页上下文
    -> 和本地数据库中的 tweet_id / published_at 做比较
    -> 如果没有新推文：直接结束，不调用 DeepSeek
    -> 如果有新推文：调用 DeepSeek 生成中文翻译 + 点评
    -> 推送到飞书
    -> 写入 SQLite，标记为已处理

静默时段：
  01:00-08:00（本地时区）
    -> 不抓取
    -> 不调用 DeepSeek

08:00 之后：
  当天第一次有效轮询
    -> 补抓 01:00-08:00 这段时间内的新推文
    -> 按白天相同格式逐条整理成晨报
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
deploy/systemd/info-fetch-push.service
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

说明：

- `X_BROWSER_CHANNEL`
  - Windows 本机建议设为 `msedge`
  - Linux 服务器建议留空，直接使用 Playwright 自带 Chromium
- `X_SYSTEM_USER_DATA_PATH`
  - 仅在 Windows 本机需要
  - Linux 服务器通常留空

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

## 防重机制

当前防重逻辑是双层判断：

1. 先按账号读取数据库里最新的 `published_at`
2. 只处理比该时间更晚的新推文
3. 再用 `tweet_id` 做最终去重

这样可以避免：

- 已经处理过的推文重复调用 DeepSeek
- 新加账号时不断回溯历史推文
- 服务重启后重复推送旧内容

## 推送格式

单条推文默认推送为：

```text
[标题]
作者：显示名 (@username)
时间：发布时间
标签：标签1 / 标签2
推文翻译：完整中文翻译
回复对象：...（如果有）
引用推文作者：...（如果有）
引用推文内容：...（如果有）
点评：中文解读
原链接：https://x.com/...
```

夜间汇总会复用同样的单条格式，只是把多条内容拼成一条晨报消息。

## Windows 本机使用

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

Windows 本机推荐：

```dotenv
X_BROWSER_CHANNEL=msedge
X_HEADLESS=true
LOCAL_TIMEZONE=Asia/Shanghai
```

至少填写：

- `DEEPSEEK_API_KEY`
- `FEISHU_WEBHOOK_URL`
- `FEISHU_BOT_SECRET`（如果飞书机器人开启签名）

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

说明：

- 这一步只支持 Windows 本机
- 导入前需要先关闭所有 Edge 窗口
- 导入后会更新 `data/x-login-state.json`

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

## Linux 服务器部署

### 推荐架构

推荐用法：

- 服务器系统：`Ubuntu 24.04 LTS`
- 浏览器：Playwright Chromium 无头模式
- 数据库：SQLite
- 登录态：从你的 Windows 本机导出的 `data/x-login-state.json`
- 常驻方式：`systemd`

### 为什么服务器上不要直接导入 Edge

`import-edge-session` 依赖：

- Windows
- 本机 Microsoft Edge 用户资料

因此服务器上不要执行这个命令。服务器应只使用已经导出的：

- `data/x-login-state.json`

### 部署步骤

#### 1. 准备服务器

建议起步配置：

- `2 vCPU`
- `4 GB RAM`
- `Ubuntu 24.04 LTS`

#### 2. 上传项目

建议部署到：

```bash
/opt/info-fetch-push-service
```

至少需要这些文件：

- `src/`
- `config/`
- `pyproject.toml`
- `.env`
- `data/x-login-state.json`

如果你想保留现有去重状态，也一起上传：

- `data/service.db`

#### 3. 安装运行环境

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip

cd /opt/info-fetch-push-service
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
python -m playwright install-deps chromium
```

#### 4. 配置 `.env`

服务器建议这样配：

```dotenv
X_BROWSER_CHANNEL=
X_HEADLESS=true
LOCAL_TIMEZONE=Asia/Shanghai
X_LOGIN_STATE_PATH=data/x-login-state.json
X_SYSTEM_USER_DATA_PATH=
DATABASE_PATH=data/service.db
RUNTIME_CONFIG_PATH=config/runtime.json
DEEPSEEK_API_KEY=你的key
FEISHU_WEBHOOK_URL=你的webhook
FEISHU_BOT_SECRET=
```

#### 5. 从本机同步 X 登录态

先在本机执行：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main import-edge-session
```

然后把这个文件上传到服务器：

- `data/x-login-state.json`

说明：

- 登录态失效后，需要重新在本机更新一次，再同步到服务器

#### 6. 先手动试跑

```bash
cd /opt/info-fetch-push-service
source .venv/bin/activate
python -m info_fetch_push_service.main show-config
python -m info_fetch_push_service.main run-once
```

#### 7. 配置 systemd

项目已经提供模板：

- [deploy/systemd/info-fetch-push.service](/E:/claudeProject/info-fetch-push-service/deploy/systemd/info-fetch-push.service)

你可以把它复制到：

```bash
/etc/systemd/system/info-fetch-push.service
```

如果你的部署目录不是 `/opt/info-fetch-push-service`，记得先改模板里的：

- `WorkingDirectory`
- `ExecStart`

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable info-fetch-push
sudo systemctl start info-fetch-push
sudo systemctl status info-fetch-push
```

查看日志：

```bash
sudo journalctl -u info-fetch-push -f
```

### Linux 上停止服务

如果是用 systemd：

```bash
sudo systemctl stop info-fetch-push
```

如果是直接用本项目命令启动：

```bash
python -m info_fetch_push_service.main stop
```

现在 `stop` 命令已经兼容 Linux。

## 常见问题

### 1. 服务器为什么不能直接用我本机正在开的 Edge

因为服务器没有你的本机 Edge 资料，也不应该去碰你的桌面浏览器环境。服务器模式应只依赖：

- `x-login-state.json`

### 2. `x-login-state.json` 过期了怎么办

在 Windows 本机重新导出一次：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main import-edge-session
```

然后把新的 `data/x-login-state.json` 覆盖到服务器。

### 3. 服务器上 `X_BROWSER_CHANNEL` 要不要设成 `msedge`

不建议。服务器建议留空，直接用 Playwright Chromium。

### 4. 会影响现在 Windows 本机逻辑吗

不会。

这次兼容改造保持了：

- Windows 本机仍可继续使用 `msedge`
- `import-edge-session` 仍保留
- Linux 只是新增兼容路径

## 日志

主日志文件：

- `logs/service.log`

已开启日志轮转：

- 单文件约 `2 MB`
- 保留 `5` 份历史日志

## 参考文档

- [DeepSeek API Docs](https://api-docs.deepseek.com/)
- [Feishu Custom Bot](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)

## 常用命令速查

### 服务器端

查看服务状态：

```bash
systemctl status info-fetch-push
```

启动服务：

```bash
systemctl start info-fetch-push
```

重启服务：

```bash
systemctl restart info-fetch-push
```

停止服务：

```bash
systemctl stop info-fetch-push
```

立即手动执行一轮：

```bash
cd /opt/info-fetch-push-service
source .venv/bin/activate
python -m info_fetch_push_service.main run-once
```

查看当前运行配置：

```bash
cd /opt/info-fetch-push-service
source .venv/bin/activate
python -m info_fetch_push_service.main show-config
```

看 systemd 实时日志：

```bash
journalctl -u info-fetch-push -f
```

看最近 100 行 systemd 日志：

```bash
journalctl -u info-fetch-push -n 100 --no-pager
```

看程序文件日志：

```bash
tail -f /opt/info-fetch-push-service/logs/service.log
```

编译检查代码是否有语法错误：

```bash
cd /opt/info-fetch-push-service
source .venv/bin/activate
python -m compileall src
```

### Windows 本机

立即跑一轮：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main run-once
```

常驻运行：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main serve
```

停止后台服务：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main stop
```

查看当前配置：

```powershell
.venv\Scripts\python -m info_fetch_push_service.main show-config
```
