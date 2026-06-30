from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class TelegramBotClient:
    def __init__(self, token: str | None):
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required for bot publishing.")
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        reply_markup: dict | None = None,
    ) -> int | None:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        body = self._post("sendMessage", payload)
        return body.get("result", {}).get("message_id")

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        self._post("editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        self._post("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})

    def set_my_commands(self, commands: list[dict]) -> None:
        self._post("setMyCommands", {"commands": json.dumps(commands, ensure_ascii=False)})

    def get_me(self) -> dict:
        return self._get("getMe").get("result", {})

    def get_updates(self, offset: int | None = None, timeout: int = 25) -> list[dict]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        return self._get("getUpdates", params).get("result", [])

    def _get(self, method: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{method}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=35) as response:
            body = json.loads(response.read().decode("utf-8"))

        if not body.get("ok"):
            raise RuntimeError(body.get("description", "Telegram Bot API error"))
        return body

    def _post(self, method: str, payload: dict[str, Any]) -> dict:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{method}",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))

        if not body.get("ok"):
            raise RuntimeError(body.get("description", "Telegram Bot API error"))
        return body
