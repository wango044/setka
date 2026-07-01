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
            improved_body = self.improve_text(source_body or item.body, channel, metadata)
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
                metadata["tgpostai_improved"] = self._passes_quality(item.body)
                metadata["tgpostai_note"] = "Model returned unchanged text."
                metadata["tgpostai_length"] = len(item.body.strip())
                metadata.pop("tgpostai_error", None)
                store.update_metadata(item.id, metadata)
        except Exception as exc:
            metadata["tgpostai_improved"] = False
            metadata["tgpostai_error"] = str(exc)
            store.update_metadata(item.id, metadata)

        return store.get_items_by_ids([item.id])[0]

    def improve_text(
        self,
        text: str,
        channel: dict[str, Any],
        metadata: dict | None = None,
    ) -> str:
        if not self.settings.gemini_api_key:
            return text

        metadata = metadata or {}
        try:
            result = self._generate(self._prompt(text, channel, metadata))
            if self._passes_quality(result):
                return result

            retry_result = self._generate(self._repair_prompt(text, channel, result, metadata))
            if self._passes_quality(retry_result):
                return retry_result
        except Exception:
            result = ""
            retry_result = ""

        fallback = self._local_rewrite(text, channel, metadata)
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
            "\u0440\u044b\u0447\u0430\u0433 \u043a\u043e\u043d\u0442\u0440\u043e\u043b\u044f",
            "\u0445\u0432\u0430\u0442\u0438\u0442 \u043a\u043e\u0440\u043c\u0438\u0442\u044c",
            "\u043e\u0442\u043b\u043e\u0436\u0438 \u0441\u043c\u0430\u0440\u0442\u0444\u043e\u043d",
            "\u0432\u0435\u0440\u043d\u0438 \u0444\u043e\u043a\u0443\u0441",
        ]
        if any(phrase in lowered for phrase in forbidden):
            return False

        step_markers = ["1.", "2.", "3.", "\u2022", "- "]
        if sum(marker in cleaned for marker in step_markers) < 2:
            return False

        return "?" in cleaned

    def _prompt(self, text: str, channel: dict[str, Any], metadata: dict) -> str:
        brand = self.config.get("brand", {})
        generation = self.config.get("generation", {})
        min_chars = generation.get("min_post_chars", 420)
        max_chars = generation.get("max_post_chars", 900)
        return f"""
Rewrite and improve this Telegram post before publication.
Return ONLY the final improved post text. No comments, no markdown fences.

The output MUST be in natural Russian.
Length: {min_chars}-{max_chars} characters.

You are a professional Telegram content editor.
Use the TgPostAI editing approach:
- correct grammar, spelling, punctuation, and style issues;
- improve structure and readability;
- add emojis only where appropriate;
- preserve the main idea, tone, and CTA;
- adapt the text to Telegram format with short readable paragraphs.

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
- Do not use Markdown headers, bold markers, or bullet formatting that looks like an article.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}

Post metadata:
{json.dumps(metadata, ensure_ascii=False)}

Original post:
{text}
""".strip()

    def _repair_prompt(
        self,
        original: str,
        channel: dict[str, Any],
        weak_result: str,
        metadata: dict,
    ) -> str:
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

Post metadata:
{json.dumps(metadata, ensure_ascii=False)}

Original post:
{original}

Weak rewrite to avoid:
{weak_result}
""".strip()

    def _local_rewrite(
        self,
        original: str,
        channel: dict[str, Any],
        metadata: dict,
    ) -> str:
        role = channel.get("role", "")
        pillars = channel.get("content_pillars") or []
        topic = metadata.get("content_pillar") or (pillars[0] if pillars else "тема")
        post_format = str(metadata.get("format") or "").lower()
        cta = channel.get("default_cta", "Хочешь продолжение? Напиши плюс.")

        if role == "middle_of_funnel":
            if "разбор" in post_format:
                return f"""
🔍 Тема «{topic}» не работает, если ты просто читаешь советы и ничего не проверяешь.

Деньги появляются не от красивой идеи. Деньги появляются, когда ты находишь конкретную боль и предлагаешь маленькое понятное решение.

⚡ Разбор по шагам:
1. Найди одну задачу, за которую люди уже платят.
2. Сформулируй услугу в одну строку.
3. Покажи пример результата или черновик.
4. Напиши 3 людям без обещаний легких денег.

{cta}

Что разобрать глубже: где искать клиентов или как писать первый оффер?
""".strip()

            if "интерактив" in post_format:
                return f"""
💬 По теме «{topic}» легко зависнуть в теории. Поэтому выбираем направление руками.

Что тебе сейчас ближе?
А — найти первую подработку.
Б — собрать услугу на фриланс.
В — выжать пользу из нейросетей.
Г — экономить через кэшбэк и подписки.

⚡ Я разберу тот вариант, который наберет больше ответов:
1. что делать первым;
2. где не слить время;
3. какие сервисы проверить;
4. как не попасть на мусорные схемы.

Без обещаний быстрых денег. Нужен один понятный шаг, который можно сделать сегодня и проверить на практике.

Какой вариант выбираешь?
""".strip()

            if "дайджест" in post_format:
                return f"""
🎁 Вечерний мини-дайджест по теме «{topic}».

Сегодня без фантазий про быстрые деньги. Только маленькие действия, которые можно проверить за 20 минут.

⚡ Что сделать:
1. Отмени одну подписку, которой не пользуешься.
2. Найди один сервис, где можно взять микро-заказ.
3. Выпиши один навык, который уже можешь продать.
4. Сохрани одну партнерку или кэшбэк-сервис для проверки.

{cta}

Что завтра разобрать конкретнее: подработки, нейросети или экономию?
""".strip()

            return f"""
💸 Деньги в телефоне начинаются не с «секретной схемы». Они начинаются с маленькой проверки.

Тема «{topic}» полезна только тогда, когда ты превращаешь ее в действие. Не в мечту. Не в заметку. В проверку спроса.

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

        if "разбор" in post_format:
            return f"""
🔍 Тема «{topic}» упирается не в мотивацию. Она упирается в устройство среды.

Когда телефон лежит рядом, мозг постоянно держит запасной выход. Чуть стало скучно — рука уже тянется к экрану. Так фокус ломается еще до старта задачи.

⚡ Что поменять:
1. Убери телефон физически, не просто переверни экраном вниз.
2. Оставь одну вкладку и одну задачу.
3. Поставь таймер на 25 минут.
4. После таймера запиши, что реально сделал.

{cta}

Что сильнее всего ломает твой фокус: уведомления, лента или привычка проверять телефон?
""".strip()

        if "интерактив" in post_format:
            return f"""
💬 Тема «{topic}» начинается с честного ответа, а не с очередного приложения для продуктивности.

Выбери, где чаще всего сливаешь внимание:
А — утром, сразу после пробуждения.
Б — перед сном.
В — во время учебы или работы.
Г — когда появляется скука.

⚡ По самому частому варианту сделаю разбор:
1. что именно триггерит залипание;
2. как убрать первый автоматический заход;
3. чем заменить скролл без героизма.

Какой вариант твой?
""".strip()

        if "дайджест" in post_format:
            return f"""
🎁 Вечерний чек по теме «{topic}».

Тут не нужна железная сила воли. Нужна одна настройка, которая завтра уменьшит шум еще до того, как ты проснешься.

⚡ Сделай перед сном:
1. Убери телефон заряжаться не у кровати.
2. Выключи уведомления от лент на ночь.
3. Выпиши 3 задачи на завтра до открытия соцсетей.
4. Оставь на утро один первый шаг, а не список из 20 дел.

{cta}

Что обычно первым крадет твое утро: сообщения, видео или лента?
""".strip()

        return f"""
🧠 Телефон снова съел час? Проблема не в том, что ты «слабый». Проблема в среде, которая каждые пару минут дергает внимание.

Тема «{topic}» не про запретить себе все. Она про убрать лишние входы, чтобы мозг успел сделать одну нормальную задачу.

⚡ Сделай сегодня:
1. Убери телефон с рабочего места на 25 минут.
2. Выключи уведомления от лент и чатов, которые не срочные.
3. Открой только одну задачу.
4. После таймера запиши результат одной строкой.

{cta}

Где у тебя чаще всего сливается внимание: утром, перед сном или во время работы?
""".strip()
