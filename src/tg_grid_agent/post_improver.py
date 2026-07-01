from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .db import ContentItem, ContentStore
from .settings import RuntimeSettings, get_channel


class TgPostAIImprover:
    """TgPostAI-style post polish layer powered by Gemini."""

    def __init__(self, settings: RuntimeSettings, config: dict[str, Any]):
        self.settings = settings
        self.config = config

    def enabled(self) -> bool:
        generation = self.config.get("generation", {})
        return bool(generation.get("improve_before_approval", True))

    def improve_item(
        self,
        store: ContentStore,
        item: ContentItem,
        force: bool = False,
    ) -> ContentItem:
        if not self.enabled():
            return item

        metadata = dict(item.metadata)
        if metadata.get("tgpostai_improved") and not force:
            return item

        try:
            channel = get_channel(self.config, item.channel_key)
            source_body = metadata.get("original_body") if force else None
            improved_body = self.improve_text(source_body or item.body, channel)
            improved_body = improved_body.strip()
            if improved_body and improved_body != item.body.strip():
                metadata.setdefault("original_body", item.body)
                metadata["tgpostai_improved"] = True
                metadata["tgpostai_model"] = self.settings.tgpostai_model
                metadata["tgpostai_force"] = force
                metadata["tgpostai_length"] = len(improved_body)
                metadata.pop("tgpostai_error", None)
                store.update_body_and_metadata(item.id, improved_body, metadata)
            else:
                metadata["tgpostai_improved"] = False
                metadata["tgpostai_note"] = "Model returned unchanged text."
                store.update_metadata(item.id, metadata)
        except Exception as exc:
            metadata["tgpostai_improved"] = False
            metadata["tgpostai_error"] = str(exc)
            store.update_metadata(item.id, metadata)

        return store.get_items_by_ids([item.id])[0]

    def improve_text(self, text: str, channel: dict[str, Any]) -> str:
        if not self.settings.gemini_api_key:
            return text

        result = self._generate(self._prompt(text, channel))
        if self._passes_quality(result):
            return result

        retry_result = self._generate(self._repair_prompt(text, channel, result))
        if self._passes_quality(retry_result):
            return retry_result

        fallback = self._local_rewrite(text, channel)
        if self._passes_quality(fallback):
            return fallback

        raise RuntimeError(
            "TgPostAI returned a weak post twice and local rewrite failed. "
            f"Last length={len(retry_result.strip())}."
        )

    def _generate(self, prompt: str) -> str:
        model = urllib.parse.quote(self.settings.tgpostai_model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={urllib.parse.quote(self.settings.gemini_api_key)}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.45,
                "topP": 0.85,
                "maxOutputTokens": 1400,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))

        try:
            return body["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected Gemini response: {body}") from exc

    def _passes_quality(self, text: str) -> bool:
        generation = self.config.get("generation", {})
        min_chars = int(generation.get("min_post_chars", 420))
        cleaned = text.strip()
        if len(cleaned) < min_chars:
            return False

        lowered = cleaned.lower()
        forbidden = [
            "рычаг контроля",
            "хватит кормить",
            "отложи смартфон",
            "верни фокус",
        ]
        if any(phrase in lowered for phrase in forbidden):
            return False

        step_markers = ["1.", "2.", "3.", "•", "- "]
        if sum(marker in cleaned for marker in step_markers) < 2:
            return False

        return "?" in cleaned

    def _prompt(self, text: str, channel: dict[str, Any]) -> str:
        brand = self.config.get("brand", {})
        generation = self.config.get("generation", {})
        min_chars = generation.get("min_post_chars", 420)
        max_chars = generation.get("max_post_chars", 900)
        return f"""
Rewrite and improve this Telegram post before publication.
Return ONLY the final improved post text. No comments, no markdown fences.

The output MUST be in natural Russian.
Length: {min_chars}-{max_chars} characters.

Quality requirements:
- It must be a useful Telegram post, not a slogan.
- Start with a sharp hook.
- Explain the problem in 1-2 short paragraphs.
- Give 3-5 concrete steps the reader can do today.
- Keep short sentences.
- Use emoji at the start of paragraphs when natural.
- Finish with a question to the audience.
- Preserve the original meaning and CTA.
- Do not invent facts, numbers, cases, prices, or guarantees.
- Avoid empty motivational phrases.
- Avoid these phrases: "рычаг контроля", "хватит кормить", "отложи смартфон", "верни фокус".
- No clickbait.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}

Original post:
{text}
""".strip()

    def _repair_prompt(self, original: str, channel: dict[str, Any], weak_result: str) -> str:
        generation = self.config.get("generation", {})
        min_chars = generation.get("min_post_chars", 420)
        max_chars = generation.get("max_post_chars", 900)
        return f"""
The previous rewrite was too weak or too short.
Write a stronger Telegram post in Russian.
Return ONLY the final post.

Required length: {min_chars}-{max_chars} characters.
Required structure:
1. Hook.
2. Short explanation.
3. List of 3-5 concrete actions.
4. Final question.

Do not use vague slogans.
Do not use: "рычаг контроля", "хватит кормить", "отложи смартфон", "верни фокус".

Channel:
{json.dumps(channel, ensure_ascii=False)}

Original post:
{original}

Weak rewrite to avoid:
{weak_result}
""".strip()

    def _local_rewrite(self, original: str, channel: dict[str, Any]) -> str:
        role = channel.get("role", "")
        name = channel.get("name", "канал")
        pillars = channel.get("content_pillars") or []
        topic = pillars[0] if pillars else "тема"
        cta = channel.get("default_cta", "Хочешь продолжение? Напиши плюс.")

        if role == "middle_of_funnel":
            return f"""
💸 Деньги в телефоне начинаются не с «секретной схемы». Они начинаются с маленькой проверки.

Ты берешь тему «{topic}» и не фантазируешь про быстрый доход. Ты проверяешь, где уже есть спрос, что ты можешь сделать сегодня и кому это можно предложить без спама.

⚡ Мини-план на вечер:
1. Выпиши один навык, который можешь продать как услугу.
2. Найди 3 примера людей, которые уже на этом зарабатывают.
3. Сформулируй оффер в одну строку.
4. Напиши 3 потенциальным клиентам или сохрани площадку для отклика.

{cta}

Что разобрать следующим: фриланс, нейросети или кэшбэк?
""".strip()

        if role == "core_private":
            return f"""
🧩 Сложная задача перестает давить, когда у нее появляется структура.

По теме «{topic}» не нужно держать все в голове. Нужен короткий документ, где видно цель, первый шаг и следующий контрольный срок.

⚡ Забери схему:
1. Что нужно получить на выходе?
2. Что уже есть сейчас?
3. Какой минимальный результат нужен сегодня?
4. Что мешает начать?
5. Кому и что нужно отправить дальше?

{cta}

Какую задачу разложить по этой схеме первой?
""".strip()

        return f"""
🧠 Телефон снова съел час? Проблема не в том, что ты «слабый». Проблема в среде, которая каждые пару минут дергает внимание.

Цифровой детокс — это не удалить все приложения и уйти в лес. Это убрать лишние входы, чтобы мозг успел сделать одну нормальную задачу.

⚡ Сделай сегодня:
1. Убери телефон с рабочего места на 25 минут.
2. Выключи уведомления от лент и чатов, которые не срочные.
3. Открой только одну задачу.
4. После таймера запиши результат одной строкой.

{cta}

Где у тебя чаще всего сливается внимание: утром, перед сном или во время работы?
""".strip()
