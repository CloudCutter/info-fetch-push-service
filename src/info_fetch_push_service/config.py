from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for pre-install bootstrap flows
    def load_dotenv() -> bool:
        return False


DEFAULT_SUMMARY_STYLE_PROMPT = (
    "Write the summary in Chinese for an investment-focused reader. "
    "First determine whether the post explicitly or implicitly recommends a stock, ETF, sector, or investment theme. "
    "If yes, identify the target, summarize the recommendation reason, and infer why the author is recommending it now. "
    "If no direct stock is mentioned, summarize the market view, sector implication, and possible watchlist direction. "
    "Return one short title and 2 to 4 high-signal sentences."
)


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    return [str(item).strip().lstrip("@") for item in items if str(item).strip()]


@dataclass(slots=True)
class StaticSettings:
    x_browser_channel: str | None
    x_headless: bool
    x_login_state_path: Path
    database_path: Path
    runtime_config_path: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_default_model: str
    feishu_webhook_url: str
    feishu_bot_secret: str | None

    @classmethod
    def load(cls) -> "StaticSettings":
        load_dotenv(override=True)

        return cls(
            x_browser_channel=os.getenv("X_BROWSER_CHANNEL", "msedge").strip() or None,
            x_headless=_parse_bool(os.getenv("X_HEADLESS"), True),
            x_login_state_path=Path(os.getenv("X_LOGIN_STATE_PATH", "data/x-login-state.json")),
            database_path=Path(os.getenv("DATABASE_PATH", "data/service.db")),
            runtime_config_path=Path(os.getenv("RUNTIME_CONFIG_PATH", "config/runtime.json")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            deepseek_default_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
            feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
            feishu_bot_secret=os.getenv("FEISHU_BOT_SECRET", "").strip() or None,
        )

    def ensure_directories(self) -> None:
        self.x_login_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)

    def validate_runtime_dependencies(self) -> None:
        missing = []
        if not self.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
        if not self.feishu_webhook_url:
            missing.append("FEISHU_WEBHOOK_URL")
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")


@dataclass(slots=True)
class RuntimeSettings:
    service_enabled: bool
    x_usernames: list[str]
    x_poll_interval_seconds: int
    x_fetch_limit: int
    deepseek_model: str
    summary_style_prompt: str
    feishu_mention_all: bool

    def validate(self) -> None:
        if self.service_enabled and not self.x_usernames:
            raise ValueError("Runtime config must include at least one X username when service_enabled is true.")
        if self.x_poll_interval_seconds <= 0:
            raise ValueError("x_poll_interval_seconds must be greater than 0.")
        if self.x_fetch_limit <= 0:
            raise ValueError("x_fetch_limit must be greater than 0.")
        if not self.deepseek_model:
            raise ValueError("deepseek_model must not be empty.")
        if not self.summary_style_prompt.strip():
            raise ValueError("summary_style_prompt must not be empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeConfigProvider:
    def __init__(self, config_path: Path, default_model: str) -> None:
        self.config_path = config_path
        self.default_model = default_model

    def load(self) -> RuntimeSettings:
        payload = self._read_json()
        runtime = RuntimeSettings(
            service_enabled=_parse_bool(payload.get("service_enabled"), True),
            x_usernames=_parse_list(payload.get("x_usernames")),
            x_poll_interval_seconds=int(payload.get("x_poll_interval_seconds", 600)),
            x_fetch_limit=int(payload.get("x_fetch_limit", 5)),
            deepseek_model=str(payload.get("deepseek_model", self.default_model)).strip(),
            summary_style_prompt=str(
                payload.get("summary_style_prompt", DEFAULT_SUMMARY_STYLE_PROMPT)
            ).strip(),
            feishu_mention_all=_parse_bool(payload.get("feishu_mention_all"), False),
        )
        runtime.validate()
        return runtime

    def write_example(self, overwrite: bool = False) -> bool:
        if self.config_path.exists() and not overwrite:
            return False

        sample = {
            "service_enabled": True,
            "x_usernames": ["OpenAI", "xai"],
            "x_poll_interval_seconds": 600,
            "x_fetch_limit": 5,
            "deepseek_model": self.default_model,
            "summary_style_prompt": DEFAULT_SUMMARY_STYLE_PROMPT,
            "feishu_mention_all": False,
        }
        self.config_path.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return True

    def describe(self) -> dict[str, Any]:
        return self.load().to_dict()

    def _read_json(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Runtime config file does not exist: {self.config_path}. "
                "Run `info-fetch-push init-runtime-config` first."
            )

        raw = self.config_path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Runtime config must be a JSON object.")
        return data
