from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


ROOT = Path.cwd()


@dataclass(frozen=True)
class RuntimeSettings:
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_bot_token: str | None
    telegram_publish_mode: str
    bot_admin_user_ids: tuple[int, ...]
    telegram_session_name: str
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    openai_image_model: str
    ollama_base_url: str
    ollama_model: str | None
    gemini_api_key: str | None
    tgpostai_model: str
    timezone: str
    session_dir: Path
    db_path: Path


def load_settings(require_telegram: bool = True) -> RuntimeSettings:
    load_dotenv()

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or None
    if require_telegram and not bot_token and (not api_id or not api_hash):
        raise RuntimeError(
            "Set TELEGRAM_BOT_TOKEN, or set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env."
        )

    session_dir = ROOT / "sessions"
    session_dir.mkdir(exist_ok=True)

    db_path = Path(os.getenv("TG_GRID_DB_PATH", str(ROOT / "tg_grid.sqlite3")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    return RuntimeSettings(
        telegram_api_id=int(api_id) if api_id else None,
        telegram_api_hash=api_hash,
        telegram_bot_token=bot_token,
        telegram_publish_mode=os.getenv("TELEGRAM_PUBLISH_MODE", "auto").lower(),
        bot_admin_user_ids=tuple(
            int(part.strip())
            for part in (os.getenv("BOT_ADMIN_USER_IDS") or "").split(",")
            if part.strip()
        ),
        telegram_session_name=os.getenv("TELEGRAM_SESSION_NAME", "owner"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL") or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        tgpostai_model=os.getenv("TGPOSTAI_MODEL", "gemini-2.5-flash"),
        timezone=os.getenv("TG_GRID_TIMEZONE", "Europe/Moscow"),
        session_dir=session_dir,
        db_path=db_path,
    )


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if "channels" not in data or not isinstance(data["channels"], list):
        raise ValueError("Config must contain a channels list.")

    return data


def get_channel(config: dict[str, Any], key: str) -> dict[str, Any]:
    for channel in config.get("channels", []):
        if channel.get("key") == key:
            return channel
    raise KeyError(f"Channel '{key}' not found in config.")
