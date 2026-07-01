from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .bot_client import TelegramBotClient
from .content_agent import ContentAgent
from .db import ContentItem, ContentStore
from .post_improver import TgPostAIImprover
from .settings import RuntimeSettings


@dataclass(frozen=True)
class ChannelInfo:
    key: str
    name: str


class AdminBot:
    def __init__(
        self,
        bot: TelegramBotClient,
        store: ContentStore,
        settings: RuntimeSettings,
        config: dict,
        channels: list[dict],
    ):
        self.bot = bot
        self.store = store
        self.settings = settings
        self.config = config
        self.channels = [
            ChannelInfo(channel["key"], channel.get("name", channel["key"]))
            for channel in channels
            if channel.get("key")
        ]
        self.channel_names = {channel.key: channel.name for channel in self.channels}
        self.config_channels = channels
        self.improver = TgPostAIImprover(settings, config)

    def run(self, once: bool = False) -> None:
        self.store.init()
        self.bot.set_my_commands(
            [
                {"command": "start", "description": "Открыть панель"},
                {"command": "posts", "description": "Черновики по каналам"},
                {"command": "cancel", "description": "Отменить редактирование"},
            ]
        )
        offset = self._get_offset()
        while True:
            updates = self.bot.get_updates(offset=offset, timeout=25)
            for update in updates:
                offset = update["update_id"] + 1
                self._set_offset(offset)
                try:
                    self.handle_update(update)
                except Exception as exc:
                    self._notify_update_error(update, exc)
            if once:
                return
            time.sleep(1)

    def handle_update(self, update: dict) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return
        if "message" in update:
            self._handle_message(update["message"])

    def _handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        from_user = message.get("from", {})
        chat_id = chat.get("id")
        user_id = from_user.get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not user_id:
            return

        if chat.get("type") != "private":
            return

        if not self._is_admin(user_id):
            self.bot.send_message(
                chat_id,
                "Доступ закрыт. Первый /start владельца закрепляет админа, либо укажи BOT_ADMIN_USER_IDS в .env.",
            )
            return

        session = self.store.get_bot_session(chat_id)
        editing_item_id = session.get("editing_item_id")
        if editing_item_id and text != "/cancel":
            self.store.update_body(int(editing_item_id), text)
            self.store.set_bot_session(chat_id, {})
            item = self._get_item(int(editing_item_id))
            self.bot.send_message(chat_id, "Сохранил новую версию поста.")
            self._send_item(chat_id, item)
            return

        if text in {"/start", "меню", "Меню"}:
            self._send_home(chat_id)
            return
        if text == "/posts":
            self._send_channels(chat_id)
            return
        if text == "/cancel":
            self.store.set_bot_session(chat_id, {})
            self.bot.send_message(chat_id, "Ок, редактирование отменено.", self._home_keyboard())
            return

        self._send_home(chat_id)

    def _handle_callback(self, query: dict) -> None:
        query_id = query["id"]
        from_user = query.get("from", {})
        user_id = from_user.get("id")
        message = query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        data = query.get("data", "")
        if not chat_id or not user_id:
            return

        if not self._is_admin(user_id):
            self.bot.answer_callback_query(query_id, "Нет доступа.")
            return

        self.bot.answer_callback_query(query_id)

        if data == "home":
            self._edit_or_send(chat_id, message_id, self._home_text(), self._home_keyboard())
            return
        if data == "channels":
            self._edit_or_send(chat_id, message_id, "Выбери канал:", self._channels_keyboard())
            return
        if data == "generate_2d":
            self.bot.send_message(chat_id, "Генерирую посты на 2 суток. Это может занять немного времени.")
            created = self._generate_two_days()
            self.bot.send_message(chat_id, f"Готово. Создал 🔴 {created} не одобренных постов.", self._home_keyboard())
            return
        if data.startswith("channel:"):
            channel_key = data.split(":", 1)[1]
            self._send_channel_posts(chat_id, channel_key, message_id)
            return
        if data.startswith("item:"):
            item_id = int(data.split(":", 1)[1])
            self._send_item(chat_id, self._get_item(item_id), message_id)
            return
        if data.startswith("edit:"):
            item_id = int(data.split(":", 1)[1])
            self.store.set_bot_session(chat_id, {"editing_item_id": item_id})
            self.bot.send_message(
                chat_id,
                "Отправь новым сообщением полный текст поста. Он заменит старую версию.\n\n/cancel — отменить.",
            )
            return
        if data.startswith("approve:"):
            item_id = int(data.split(":", 1)[1])
            try:
                self.bot.send_message(chat_id, "Улучшаю пост через TgPostAI перед одобрением...")
                self.improver.improve_item(self.store, self._get_item(item_id))
                self.store.approve([item_id])
                item = self._get_item(item_id)
                self._send_item(chat_id, item, message_id)
            except Exception as exc:
                self.bot.send_message(chat_id, f"Не смог одобрить пост [{item_id}]: {exc}")
            return
        if data.startswith("improve:"):
            item_id = int(data.split(":", 1)[1])
            try:
                self.bot.send_message(chat_id, "Улучшаю пост через TgPostAI...")
                item = self.improver.improve_item(self.store, self._get_item(item_id), force=True)
                self._send_item(chat_id, item, message_id)
            except Exception as exc:
                self.bot.send_message(chat_id, f"Не смог улучшить пост [{item_id}]: {exc}")
            return

    def _send_home(self, chat_id: int) -> None:
        self.bot.send_message(chat_id, self._home_text(), self._home_keyboard())

    def _send_channels(self, chat_id: int) -> None:
        self.bot.send_message(chat_id, "Выбери канал:", self._channels_keyboard())

    def _send_channel_posts(
        self,
        chat_id: int,
        channel_key: str,
        message_id: int | None = None,
    ) -> None:
        drafts = self.store.list_items(status="draft", channel_key=channel_key, limit=10)
        approved = self.store.list_items(status="approved", channel_key=channel_key, limit=10)
        queued = self.store.list_items(status="queued", channel_key=channel_key, limit=10)
        items = [*drafts, *approved, *queued]
        text = (
            f"{self.channel_names.get(channel_key, channel_key)}\n\n"
            f"🔴 Не одобрены: {len(drafts)}\n"
            f"🟢 Одобрены: {len(approved)}\n"
            f"🟡 В очереди: {len(queued)}"
        )
        buttons = [
            [{"text": self._item_button(item), "callback_data": f"item:{item.id}"}]
            for item in items[:20]
        ]
        buttons.append([{"text": "Назад к каналам", "callback_data": "channels"}])
        self._edit_or_send(chat_id, message_id, text, {"inline_keyboard": buttons})

    def _send_item(
        self,
        chat_id: int,
        item: ContentItem,
        message_id: int | None = None,
    ) -> None:
        text = self._item_text(item)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Редактировать", "callback_data": f"edit:{item.id}"},
                    {"text": "Улучшить", "callback_data": f"improve:{item.id}"},
                ],
                [
                    {"text": "Одобрить", "callback_data": f"approve:{item.id}"},
                ],
                [
                    {
                        "text": "К списку",
                        "callback_data": f"channel:{item.channel_key}",
                    }
                ],
            ]
        }
        self._edit_or_send(chat_id, message_id, text, keyboard)

    def _edit_or_send(
        self,
        chat_id: int,
        message_id: int | None,
        text: str,
        keyboard: dict | None,
    ) -> None:
        if message_id:
            try:
                self.bot.edit_message_text(chat_id, message_id, text[:4000], keyboard)
            except Exception:
                self.bot.send_message(chat_id, text[:4000], keyboard)
        else:
            self.bot.send_message(chat_id, text[:4000], keyboard)

    def _notify_update_error(self, update: dict, exc: Exception) -> None:
        message = update.get("message") or update.get("callback_query", {}).get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        if chat_id:
            try:
                self.bot.send_message(chat_id, f"Ошибка в админке: {exc}")
            except Exception:
                pass

    def _home_text(self) -> str:
        draft_count = len(self.store.list_items(status="draft", limit=1000))
        approved_count = len(self.store.list_items(status="approved", limit=1000))
        queued_count = len(self.store.list_items(status="queued", limit=1000))
        return (
            "Панель управления сеткой\n\n"
            f"🔴 Не одобрены: {draft_count}\n"
            f"🟢 Одобрены: {approved_count}\n"
            f"🟡 В очереди: {queued_count}\n\n"
            "Выбери действие."
        )

    def _home_keyboard(self) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "Посты по каналам", "callback_data": "channels"}],
                [{"text": "Сделать план на 2 суток", "callback_data": "generate_2d"}],
            ]
        }

    def _channels_keyboard(self) -> dict:
        buttons = [
            [{"text": channel.name, "callback_data": f"channel:{channel.key}"}]
            for channel in self.channels
        ]
        buttons.append([{"text": "Главное меню", "callback_data": "home"}])
        return {"inline_keyboard": buttons}

    def _item_text(self, item: ContentItem) -> str:
        channel_name = self.channel_names.get(item.channel_key, item.channel_key)
        return (
            f"[{item.id}] {channel_name}\n"
            f"Статус: {self._status_label(item.status)}\n"
            f"Название: {item.title}\n\n"
            f"{item.body}"
        )

    def _item_button(self, item: ContentItem) -> str:
        return f"{self._status_label(item.status)} [{item.id}] {item.title[:35]}"

    @staticmethod
    def _status_label(status: str) -> str:
        labels = {
            "draft": "🔴 не одобрен",
            "approved": "🟢 одобрен",
            "queued": "🟡 в очереди",
            "published": "✅ опубликован",
            "failed": "⚠️ ошибка",
        }
        return labels.get(status, status)

    def _generate_two_days(self) -> int:
        agent = ContentAgent(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
            image_model=self.settings.openai_image_model,
            base_url=self.settings.openai_base_url,
            ollama_base_url=self.settings.ollama_base_url,
            ollama_model=self.settings.ollama_model,
            gemini_api_key=self.settings.gemini_api_key,
            gemini_model=self.settings.tgpostai_model,
        )
        created = 0
        for channel in self.config_channels:
            if not channel.get("key"):
                continue
            count = int(channel.get("daily_target_posts", 4)) * 2
            items = agent.generate_posts(self.config, channel, count)
            created += len(self.store.add_many(channel["key"], items))
        return created

    def _get_item(self, item_id: int) -> ContentItem:
        items = self.store.get_items_by_ids([item_id])
        if not items:
            raise RuntimeError(f"Post {item_id} not found.")
        return items[0]

    def _is_admin(self, user_id: int) -> bool:
        configured = set(self.settings.bot_admin_user_ids)
        if configured:
            return user_id in configured

        stored = self.store.get_state("bot_admin_user_ids")
        if stored:
            return user_id in set(json.loads(stored))

        self.store.set_state("bot_admin_user_ids", json.dumps([user_id]))
        return True

    def _get_offset(self) -> int | None:
        value = self.store.get_state("admin_bot_update_offset")
        return int(value) if value else None

    def _set_offset(self, offset: int) -> None:
        self.store.set_state("admin_bot_update_offset", str(offset))
