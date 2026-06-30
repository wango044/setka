from __future__ import annotations

import json
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class ContentAgent:
    api_key: str | None
    model: str
    image_model: str = "gpt-image-1"

    def generate_posts(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        count: int,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            return self._fallback_posts(channel, count)

        client = OpenAI(api_key=self.api_key)
        prompt = self._posts_prompt(config, channel, count)
        try:
            response = client.responses.create(model=self.model, input=prompt)
            return self._extract_json_list(response.output_text)
        except Exception as exc:
            items = self._fallback_posts(channel, count)
            for item in items:
                item["metadata"]["generation_fallback_reason"] = str(exc)
            return items

    def render_creative(
        self,
        prompt: str,
        output_path: Path,
        size: str = "1024x1024",
    ) -> Path:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required to render creatives.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        client = OpenAI(api_key=self.api_key)
        response = client.images.generate(
            model=self.image_model,
            prompt=prompt,
            size=size,
        )
        image = response.data[0]
        b64_json = getattr(image, "b64_json", None)
        if not b64_json:
            raise RuntimeError("Image API did not return base64 image data.")

        output_path.write_bytes(base64.b64decode(b64_json))
        return output_path

    def generate_video_ideas(
        self,
        config: dict[str, Any],
        topic: str,
        count: int,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            return [
                {
                    "platform": "TikTok",
                    "hook": f"3 mistakes people make with {topic}",
                    "outline": ["Open with a sharp mistake", "Show the fix", "End with one action"],
                    "production_notes": "Vertical video, direct-to-camera, captions on screen.",
                }
                for _ in range(count)
            ]

        client = OpenAI(api_key=self.api_key)
        brand = config.get("brand", {})
        prompt = f"""
Return ONLY a JSON array with {count} video ideas.
Each item must have: platform, hook, outline, production_notes, repurpose_to_telegram.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Topic:
{topic}

Balance the ideas across TikTok Shorts/Reels style and YouTube long-form.
Make ideas concrete enough that a creator can shoot them today.
"""
        response = client.responses.create(model=self.model, input=prompt)
        return self._extract_json_list(response.output_text)

    def _posts_prompt(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        count: int,
    ) -> str:
        generation = config.get("generation", {})
        brand = config.get("brand", {})
        max_chars = generation.get("max_post_chars", 1200)
        include_creative = generation.get("include_creative_prompt", True)

        return f"""
Return ONLY a JSON array with exactly {count} Telegram post drafts.
Each item must have:
- title: short internal title
- body: final Telegram post text, max {max_chars} characters
- creative_prompt: prompt for an image/card/video creative, or null
- metadata: object with content_pillar, format, target_emotion

Rules:
- Write in Russian unless the channel context clearly says otherwise.
- No fake facts, fake numbers, or fake testimonials.
- Keep Telegram formatting simple.
- Vary formats: tactical note, story, checklist, opinion, mini-case, question.
- Include a clear CTA only when natural.
- creative_prompt required: {include_creative}

Brand:
{json.dumps(brand, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}
"""

    def _extract_json_list(self, text: str) -> list[dict[str, Any]]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()

        data = json.loads(cleaned)
        if not isinstance(data, list):
            raise ValueError("Model returned JSON, but not a list.")
        return [self._normalize_item(item) for item in data]

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if "title" not in item and "hook" in item:
            item["title"] = item["hook"]
        if "body" not in item:
            outline = item.get("outline", [])
            item["body"] = "\n".join(outline) if isinstance(outline, list) else str(outline)
        item.setdefault("creative_prompt", None)
        item.setdefault("metadata", {})
        return item

    def _fallback_posts(self, channel: dict[str, Any], count: int) -> list[dict[str, Any]]:
        pillars = channel.get("content_pillars") or ["useful idea"]
        cta = channel.get("default_cta", "Напиши плюс, если нужно продолжение.")
        name = channel.get("name", channel.get("key", "канал"))
        role = channel.get("role", "")
        templates = [
            (
                "Полезный пост",
                "🧠 {hook}\n\n⚡ Правило простое: убери один раздражитель, а не пытайся стать железным человеком.\n\n"
                "✅ Что сделать сегодня:\n"
                "1. Выключи лишние уведомления.\n"
                "2. Поставь таймер на 25 минут.\n"
                "3. Оставь один экран, одну задачу, один результат.\n\n{cta}",
            ),
            (
                "Разбор",
                "🔍 {hook}\n\nПроблема не в лени. Проблема в среде, которая дергает тебя каждые 30 секунд.\n\n"
                "Рабочая схема:\n"
                "• убери быстрый дофамин перед задачей;\n"
                "• заранее реши, что делаешь первым;\n"
                "• фиксируй маленький результат, а не настроение.\n\n{cta}",
            ),
            (
                "Интерактив",
                "💬 {hook}\n\nДавай честно: большинство сливается не потому, что задача сложная. "
                "А потому что нет понятного первого шага.\n\n"
                "Напиши в комменты, где сейчас затык: фокус, деньги, привычки или план?",
            ),
            (
                "Дайджест",
                "🎁 {hook}\n\nМини-бонус на вечер:\n"
                "• одна мысль: меньше входов, больше действий;\n"
                "• один инструмент: заметка с тремя задачами на завтра;\n"
                "• один запрет: не открывать ленту до первого результата.\n\n{cta}",
            ),
        ]
        posts: list[dict[str, Any]] = []
        for index in range(count):
            pillar = pillars[index % len(pillars)]
            title, template, hook, local_cta = self._fallback_template(role, pillar, index, cta)
            posts.append(
                {
                    "title": f"{name}: {title} #{index + 1}",
                    "body": template.format(hook=hook, cta=local_cta),
                    "creative_prompt": (
                        "Telegram post visual, bold Russian headline, clean modern editorial style, "
                        f"channel: {name}, topic: {pillar}, high contrast, no fake screenshots."
                    ),
                    "metadata": {
                        "content_pillar": pillar,
                        "format": title,
                        "target_emotion": "clarity",
                    },
                }
            )
        return posts

    def _fallback_template(
        self,
        role: str,
        pillar: str,
        index: int,
        cta: str,
    ) -> tuple[str, str, str, str]:
        if role == "middle_of_funnel":
            templates = [
                (
                    "Полезный пост",
                    "💸 {hook}\n\n⚡ Мини-проверка на сегодня:\n"
                    "1. Есть ли сервис, где ты уже умеешь что-то делать?\n"
                    "2. Можно ли упаковать это в простую услугу за 300-1000 руб?\n"
                    "3. Кому можно написать без спама и обещаний золотых гор?\n\n{cta}",
                    f"Тема «{pillar}» не про магию. Это про маленькое действие, которое можно проверить за вечер.",
                ),
                (
                    "Разбор",
                    "🔍 {hook}\n\nРабочая логика такая:\n"
                    "• сначала ищешь боль, за которую уже платят;\n"
                    "• потом делаешь микро-оффер;\n"
                    "• потом собираешь 3-5 диалогов, а не мечтаешь о пассивном доходе.\n\n{cta}",
                    f"Если хочешь заработать на теме «{pillar}», не начинай с красивой шапки профиля.",
                ),
                (
                    "Интерактив",
                    "💬 {hook}\n\nВыбери один вариант:\n"
                    "А — хочу фриланс-заказы.\n"
                    "Б — хочу экономить на сервисах.\n"
                    "В — хочу партнерки и кэшбэк.\n"
                    "Г — хочу нейросети для подработки.\n\nЧто разобрать завтра?",
                    f"Тема «{pillar}» может дать деньги только после конкретного шага.",
                ),
                (
                    "Дайджест",
                    "🎁 {hook}\n\nНа вечер:\n"
                    "• проверь одну подписку, которую можно отменить;\n"
                    "• найди один навык, который можно продать как услугу;\n"
                    "• сохрани один сервис, который экономит деньги.\n\n{cta}",
                    f"По теме «{pillar}» сегодня достаточно одного маленького финансового действия.",
                ),
            ]
            return (*templates[index % len(templates)], cta)

        if role == "core_private":
            templates = [
                (
                    "Шаблон",
                    "🧩 {hook}\n\nСтруктура:\n"
                    "1. Цель.\n"
                    "2. Первый шаг.\n"
                    "3. Контрольный срок.\n"
                    "4. Что мешает.\n"
                    "5. Следующее действие.\n\n{cta}",
                    f"Тема «{pillar}» должна превращаться в документ, а не висеть в голове.",
                ),
                (
                    "Разбор",
                    "🔍 {hook}\n\nРазбиваем задачу:\n"
                    "• что нужно получить;\n"
                    "• какие входные данные есть;\n"
                    "• какой минимальный результат нужен сегодня;\n"
                    "• кому и что отправить дальше.\n\n{cta}",
                    f"По теме «{pillar}» главное — убрать туман и оставить конкретный маршрут.",
                ),
            ]
            return (*templates[index % len(templates)], cta)

        templates = [
            (
                "Полезный пост",
                "🧠 {hook}\n\n⚡ Сделай сегодня:\n"
                "1. Убери телефон с рабочего места.\n"
                "2. Поставь таймер на 25 минут.\n"
                "3. Открой только одну задачу.\n"
                "4. После таймера запиши результат одной строкой.\n\n{cta}",
                f"Если телефон снова съел час, тема «{pillar}» поможет вернуть управление.",
            ),
            (
                "Разбор",
                "🔍 {hook}\n\nПроблема не в слабой силе воли. Проблема в среде.\n\n"
                "Что ломает фокус:\n"
                "• уведомления;\n"
                "• быстрый дофамин;\n"
                "• открытые вкладки;\n"
                "• отсутствие первого шага.\n\n{cta}",
                f"По теме «{pillar}» почти всегда выигрывает не мотивация, а настройка окружения.",
            ),
            (
                "Интерактив",
                "💬 {hook}\n\nВыбери честно:\n"
                "А — залипаю утром.\n"
                "Б — залипаю перед сном.\n"
                "В — залипаю вместо учебы/работы.\n"
                "Г — открываю телефон автоматически.\n\nГде у тебя главный слив внимания?",
                f"Тема «{pillar}» начинается с одного честного ответа.",
            ),
            (
                "Дайджест",
                "🎁 {hook}\n\nНа вечер:\n"
                "• выключи уведомления на 12 часов;\n"
                "• поставь телефон заряжаться не у кровати;\n"
                "• выпиши 3 дела на завтра до открытия ленты.\n\n{cta}",
                f"По теме «{pillar}» не нужен героизм. Нужна одна настройка среды.",
            ),
        ]
        return (*templates[index % len(templates)], cta)
