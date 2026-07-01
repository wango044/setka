from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class ContentAgent:
    api_key: str | None
    model: str
    image_model: str = "gpt-image-1"
    base_url: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    def generate_posts(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        count: int,
    ) -> list[dict[str, Any]]:
        prompt = self._posts_prompt(config, channel, count)
        errors: list[str] = []

        if self.gemini_api_key:
            try:
                text = self._generate_gemini_text(prompt, max_tokens=9000, temperature=0.9)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"Gemini: {exc}")

                try:
                    repair = self._json_repair_prompt(prompt, str(exc))
                    text = self._generate_gemini_text(repair, max_tokens=9000, temperature=0.65)
                    return self._extract_json_list(text, expected_count=count)
                except Exception as retry_exc:
                    errors.append(f"Gemini retry: {retry_exc}")

        if self.api_key:
            try:
                text = self._generate_openai_text(prompt, temperature=0.85)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"OpenAI: {exc}")

        if self.ollama_model:
            try:
                text = self._generate_ollama_text(prompt, temperature=0.85)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"Ollama: {exc}")

        items = self._fallback_posts(channel, count)
        for item in items:
            item["metadata"]["generation_fallback_reason"] = " | ".join(errors) or "No AI key configured."
        return items

    def generate_posts_from_source(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        transcript: str,
        count: int = 7,
        source_title: str | None = None,
        source_url: str | None = None,
    ) -> list[dict[str, Any]]:
        prompt = self._source_posts_prompt(config, channel, transcript, count, source_title, source_url)
        errors: list[str] = []

        if self.gemini_api_key:
            try:
                text = self._generate_gemini_text(prompt, max_tokens=9000, temperature=0.7)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"Gemini: {exc}")

        if self.api_key:
            try:
                text = self._generate_openai_text(prompt, temperature=0.7)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"OpenAI: {exc}")

        if self.ollama_model:
            try:
                text = self._generate_ollama_text(prompt, temperature=0.7)
                return self._extract_json_list(text, expected_count=count)
            except Exception as exc:
                errors.append(f"Ollama: {exc}")

        items = self._fallback_posts(channel, count)
        for item in items:
            item["metadata"]["generation_fallback_reason"] = " | ".join(errors) or "No AI provider configured."
            item["metadata"]["source_url"] = source_url
            item["metadata"]["source_title"] = source_title
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
        prompt = self._video_ideas_prompt(config, topic, count)

        if self.gemini_api_key:
            try:
                text = self._generate_gemini_text(prompt, max_tokens=5000, temperature=0.85)
                return self._extract_json_list(text, expected_count=count, validate_posts=False)
            except Exception:
                pass

        if self.api_key:
            text = self._generate_openai_text(prompt, temperature=0.85)
            return self._extract_json_list(text, expected_count=count, validate_posts=False)

        if self.ollama_model:
            text = self._generate_ollama_text(prompt, temperature=0.85)
            return self._extract_json_list(text, expected_count=count, validate_posts=False)

        return [
            {
                "platform": "TikTok",
                "hook": f"3 mistakes people make with {topic}",
                "outline": ["Open with a sharp mistake", "Show the fix", "End with one action"],
                "production_notes": "Vertical video, direct-to-camera, captions on screen.",
            }
            for _ in range(count)
        ]

    def _generate_openai_text(self, prompt: str, temperature: float) -> str:
        client = OpenAI(api_key=self.api_key, base_url=self.base_url) if self.base_url else OpenAI(api_key=self.api_key)
        if self.base_url:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response.choices[0].message.content or ""

        response = client.responses.create(
            model=self.model,
            input=prompt,
            temperature=temperature,
        )
        return response.output_text

    def _generate_ollama_text(self, prompt: str, temperature: float) -> str:
        if not self.ollama_model:
            raise RuntimeError("OLLAMA_MODEL is not configured.")

        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_ctx": 32768,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=240) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body.get("response", "")).strip()

    def _generate_gemini_text(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "topP": 0.95,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }

        errors: list[str] = []
        for model_name in self._gemini_candidate_models():
            model = urllib.parse.quote(model_name, safe="")
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={urllib.parse.quote(self.gemini_api_key)}"
            )
            request = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                errors.append(f"{model_name}: HTTP {exc.code} {details[:240]}")
                continue

            try:
                return body["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError) as exc:
                errors.append(f"{model_name}: unexpected response {body}")
                continue

        raise RuntimeError("All Gemini models failed. " + " | ".join(errors))

    def _gemini_candidate_models(self) -> list[str]:
        candidates = [
            self.gemini_model,
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
        ]
        result: list[str] = []
        for model in candidates:
            if model and model not in result:
                result.append(model)
        return result

    def _posts_prompt(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        count: int,
    ) -> str:
        generation = config.get("generation", {})
        brand = config.get("brand", {})
        calendar = config.get("calendar", {})
        max_chars = int(generation.get("max_post_chars", 900))
        min_chars = int(generation.get("min_post_chars", 420))
        include_creative = bool(generation.get("include_creative_prompt", True))

        return f"""
You are a senior Telegram editor and content strategist.
Create exactly {count} ready-to-review Telegram post drafts for one channel.
Return ONLY valid JSON: an array of objects. No markdown fence. No comments.

Each object schema:
{{
  "title": "short internal Russian title, no numbering",
  "body": "final Telegram post text in natural Russian",
  "creative_prompt": "short image/card/video creative prompt, or null",
  "metadata": {{
    "content_pillar": "pillar",
    "format": "format",
    "angle": "angle",
    "slot_role": "slot role",
    "target_emotion": "emotion"
  }}
}}

Hard quality rules:
- Body length: {min_chars}-{max_chars} characters.
- Russian language only in body and title.
- Style: дерзко, экспертно, по делу. Без воды. Короткие предложения.
- Start most paragraphs with a relevant emoji, but do not turn the post into emoji soup.
- End every body with a real question to the audience.
- No clickbait, no fake facts, no fake numbers, no fake testimonials, no guaranteed income.
- Do not use markdown headings, "**", "##", or article-style formatting.
- Do not write "пост #", "лайфхак #", "в этом посте", or any meta text.
- Avoid weak slogans and banned phrases: "рычаг контроля", "хватит кормить", "отложи смартфон", "верни фокус".
- The posts must be substantially different from each other.

Anti-repetition rules:
- No two posts may use the same first sentence structure.
- No two posts may use the same list structure.
- No two posts may end with the same question.
- Use a unique angle for each item, cycling through:
  contrarian take, concrete checklist, mini-story, teardown, myth, mistake,
  prompt, challenge, resource, personal experiment, comparison, poll,
  case sketch, script, before/after.
- Use slot roles from the calendar when possible: useful post, deep breakdown,
  interactive question, evening digest or bonus content.

Channel-specific direction:
- If the channel is about focus/detox, make the advice practical: environment,
  triggers, screen habits, attention, study/work routines, sleep boundaries.
- If the channel is about money, make it legal and realistic: freelance,
  AI tools, cashback, subscriptions, small services, safe first steps.
  Never promise income. Prefer "test", "check", "try", "compare".
- If the channel is private/core, make it more tactical: templates,
  checklists, task breakdowns, operating steps.

Creative prompt required: {include_creative}.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Calendar:
{json.dumps(calendar, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}
""".strip()

    def _source_posts_prompt(
        self,
        config: dict[str, Any],
        channel: dict[str, Any],
        transcript: str,
        count: int,
        source_title: str | None,
        source_url: str | None,
    ) -> str:
        generation = config.get("generation", {})
        brand = config.get("brand", {})
        max_chars = int(generation.get("max_post_chars", 1200))
        min_chars = int(generation.get("min_post_chars", 420))
        transcript = transcript[:70000]

        return f"""
You are a philosophical Telegram editor.
Turn one long video transcript into exactly {count} independent Telegram posts for the week.
Return ONLY valid JSON: an array of objects. No markdown fence. No comments.

Each object schema:
{{
  "title": "short internal Russian title, no numbering",
  "body": "final Telegram post text with Telegram-safe HTML",
  "creative_prompt": "short visual prompt for a Telegram card, or null",
  "metadata": {{
    "source_title": "source title",
    "source_url": "source url",
    "idea": "main extracted idea",
    "quote_or_thesis": "short quote or paraphrased thesis from the transcript",
    "practical_step": "one action reader can take"
  }}
}}

Hard rules:
- Russian language only.
- Body length: {min_chars}-{max_chars} characters.
- Use Telegram-safe HTML only: <b>...</b>, <i>...</i>, line breaks. Do not use Markdown.
- Start body with a strong <b>headline</b>.
- Each post must contain:
  1. one clear idea extracted from the transcript;
  2. one short quote or careful paraphrase of the speaker's thesis;
  3. one practical step for the reader;
  4. one final question.
- Do not invent facts, statistics, names, prices, or testimonials.
- Do not repeat the same structure or opener across posts.
- Do not mention that this is "post #".
- Keep posts suitable for Telegram publication.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}

Source title:
{source_title or ""}

Source URL:
{source_url or ""}

Transcript:
{transcript}
""".strip()

    def _video_ideas_prompt(
        self,
        config: dict[str, Any],
        topic: str,
        count: int,
    ) -> str:
        brand = config.get("brand", {})
        return f"""
Return ONLY a JSON array with exactly {count} video ideas.
Each item must have: platform, hook, outline, production_notes, repurpose_to_telegram.

Write in Russian.
Balance the ideas across TikTok Shorts/Reels style and YouTube long-form.
Make ideas concrete enough that a creator can shoot them today.
Avoid fake results, clickbait, and guaranteed income.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Topic:
{topic}
""".strip()

    def _json_repair_prompt(self, original_prompt: str, error: str) -> str:
        return f"""
Your previous answer failed validation: {error}

Try again. Return ONLY valid JSON array. Follow every original requirement.

Original task:
{original_prompt}
""".strip()

    def _extract_json_list(
        self,
        text: str,
        expected_count: int | None = None,
        validate_posts: bool = True,
    ) -> list[dict[str, Any]]:
        cleaned = self._clean_json_text(text)
        data = json.loads(cleaned)
        if not isinstance(data, list):
            raise ValueError("Model returned JSON, but not a list.")

        items = [self._normalize_item(item) for item in data]
        if expected_count is not None and len(items) != expected_count:
            raise ValueError(f"Expected {expected_count} items, got {len(items)}.")

        if validate_posts:
            self._validate_variety(items)
        return items

    def _clean_json_text(self, text: str) -> str:
        cleaned = text.strip()
        fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
        if fence:
            return fence.group(1).strip()

        if cleaned.startswith("[") and cleaned.endswith("]"):
            return cleaned

        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            return match.group(0)
        return cleaned

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("Model returned a non-object item.")

        if "title" not in item and "hook" in item:
            item["title"] = item["hook"]
        if "body" not in item:
            outline = item.get("outline", [])
            item["body"] = "\n".join(outline) if isinstance(outline, list) else str(outline)

        item["title"] = str(item.get("title") or "Черновик").strip()
        item["body"] = str(item.get("body") or "").strip()
        item.setdefault("creative_prompt", None)
        item.setdefault("metadata", {})
        if not isinstance(item["metadata"], dict):
            item["metadata"] = {"raw_metadata": item["metadata"]}
        return item

    def _validate_variety(self, items: list[dict[str, Any]]) -> None:
        if not items:
            raise ValueError("Model returned no items.")

        openers: list[str] = []
        for index, item in enumerate(items, start=1):
            body = item.get("body", "").strip()
            if len(body) < 120:
                raise ValueError(f"Item {index} is too short.")
            first_line = body.splitlines()[0].lower()
            opener = " ".join(re.findall(r"[\wа-яА-ЯёЁ]+", first_line)[:7])
            if opener:
                openers.append(opener)

        duplicates = {opener for opener in openers if openers.count(opener) > 1}
        if duplicates and len(items) > 2:
            raise ValueError(f"Duplicate opening pattern: {sorted(duplicates)[0]}")

    def _fallback_posts(self, channel: dict[str, Any], count: int) -> list[dict[str, Any]]:
        pillars = channel.get("content_pillars") or ["полезная идея"]
        cta = channel.get("default_cta", "Что разобрать следующим?")
        name = channel.get("name", channel.get("key", "Канал"))
        role = channel.get("role", "")
        formats = [
            ("Миф", "myth"),
            ("Чек-лист", "checklist"),
            ("Разбор ошибки", "mistake"),
            ("Мини-эксперимент", "experiment"),
            ("Вопрос аудитории", "poll"),
            ("До/после", "before_after"),
            ("Скрипт", "script"),
            ("Ресурс", "resource"),
        ]

        posts: list[dict[str, Any]] = []
        for index in range(count):
            pillar = pillars[index % len(pillars)]
            title, angle = formats[index % len(formats)]
            body = self._fallback_body(role, pillar, cta, angle)
            posts.append(
                {
                    "title": f"{name}: {title} - {pillar}",
                    "body": body,
                    "creative_prompt": (
                        "Telegram visual card, bold Russian headline, clean modern editorial style, "
                        f"channel: {name}, topic: {pillar}, high contrast, no fake screenshots."
                    ),
                    "metadata": {
                        "content_pillar": pillar,
                        "format": title,
                        "angle": angle,
                        "target_emotion": "clarity",
                    },
                }
            )
        return posts

    def _fallback_body(self, role: str, pillar: str, cta: str, angle: str) -> str:
        if role == "middle_of_funnel":
            return self._money_fallback(pillar, cta, angle)
        if role == "core_private":
            return self._core_fallback(pillar, cta, angle)
        return self._focus_fallback(pillar, cta, angle)

    def _focus_fallback(self, pillar: str, cta: str, angle: str) -> str:
        variants = {
            "myth": f"""🧠 Миф: чтобы наладить {pillar}, нужна железная дисциплина.

На практике чаще решает не характер, а среда. Если телефон лежит рядом, мозг держит быстрый выход в ленту.

⚡ Проверь сегодня:
1. Убери телефон из поля зрения на 25 минут.
2. Оставь одну вкладку и одну задачу.
3. Запиши результат одной строкой.

Не оценивай себя по настроению. Смотри только на факт: получилось ли убрать один лишний вход.

{cta}

Где у тебя чаще всего ломается внимание?""",
            "checklist": f"""✅ Быстрый чек по теме «{pillar}».

Не пытайся стать идеальным. Убери один вход, который крадет внимание чаще всего.

⚡ Мини-план:
1. Выключи уведомления от лент.
2. Поставь зарядку не у кровати.
3. Открой задачу до открытия соцсетей.
4. После работы отметь, что реально сделал.

Если сорвался, не начинай день заново. Просто вернись к одному следующему действию.

Фокус чинится повтором, а не идеальным стартом.

Что из этого проще внедрить сегодня?""",
            "mistake": f"""🚫 Главная ошибка в теме «{pillar}» — начинать с мотивации.

Мотивация скачет. Настройки среды держатся дольше.

⚡ Сделай проще:
1. Удали один лишний ярлык с первого экрана.
2. Включи режим фокуса на учебу или работу.
3. Оставь себе понятный первый шаг на утро.

Не делай ставку на настроение. Сделай так, чтобы плохому настроению было сложнее управлять твоим экраном.

{cta}

Какой триггер чаще всего утаскивает тебя в телефон?""",
            "experiment": f"""🧪 Эксперимент на сегодня: проверь тему «{pillar}» без героизма.

Не надо удалять все приложения и обещать себе новую жизнь. Возьми один отрезок дня и сделай его тише.

⚡ Правила на 40 минут:
1. Телефон уходит в другую комнату.
2. На экране остается одна задача.
3. Если тянет проверить ленту, ставишь отметку на бумаге.
4. В конце пишешь: что сделал и сколько раз сорвался.

Это не про стыд. Это диагностика.

Что думаешь, сколько отметок у тебя набежит за 40 минут?""",
            "poll": f"""💬 Давай без красивых обещаний: где у тебя сильнее всего проседает {pillar}?

А — утром, когда берешь телефон сразу после сна.
Б — днем, когда задача становится скучной.
В — вечером, когда уже нет сил выбирать.
Г — ночью, когда «еще пять минут» превращаются в час.

⚡ Я разберу самый частый вариант и дам схему, как убрать первый триггер без жестких запретов.

Выбирай букву: где у тебя главный слив внимания?""",
            "before_after": f"""🔁 До: ты открываешь телефон «на минуту» и теряешь кусок дня.

После: телефон остается инструментом, а не кнопкой побега от скуки.

⚡ Что поменять в теме «{pillar}»:
1. До задачи убери быстрые приложения с первого экрана.
2. Во время задачи держи рядом бумагу для лишних мыслей.
3. После задачи дай себе 10 минут на ленту, но только после результата.

Смысл простой: не запрещать всё, а поменять порядок.

Какой пункт у тебя сработает быстрее всего?""",
            "script": f"""🗣 Скрипт для себя, когда рука сама тянется к телефону.

Не спорь с мозгом. Дай ему короткую команду.

⚡ Фраза:
«Я могу открыть ленту через 15 минут. Сейчас делаю только первый шаг».

Дальше сразу действие:
1. Назови задачу вслух.
2. Открой нужный файл или тетрадь.
3. Поставь таймер.
4. Запиши одну строку результата.

В теме «{pillar}» выигрывает не тот, кто терпит дольше. Выигрывает тот, кто быстрее возвращается к шагу.

Попробуешь сегодня такой скрипт?""",
            "resource": f"""🧰 Мини-набор для темы «{pillar}» без покупки новых приложений.

Тебе хватит того, что уже есть в телефоне.

⚡ Собери систему:
1. Режим фокуса — для учебы или работы.
2. Заметка — для трех задач на день.
3. Таймер — для коротких рывков по 25 минут.
4. Экранное время — чтобы видеть правду, а не ощущения.

Главное: не превращай настройку в отдельный проект. Пять минут настроил, потом работаешь.

Что первым включишь: режим фокуса, таймер или лимиты?""",
        }
        return variants.get(angle, variants["checklist"]).strip()

    def _money_fallback(self, pillar: str, cta: str, angle: str) -> str:
        variants = {
            "myth": f"""💸 Миф: в теме «{pillar}» надо сразу искать большую схему.

Реалистичный путь скучнее, зато рабочий: найти маленькую задачу, сделать аккуратно, получить первый отзыв.

⚡ Проверь сегодня:
1. Выпиши один навык, который уже умеешь.
2. Найди 3 примера похожих услуг.
3. Сформулируй оффер в одну строку.
4. Напиши без обещаний легких денег.

{cta}

Какой навык первым попробуешь упаковать?""",
            "checklist": f"""✅ Мини-чек по теме «{pillar}».

Не верь обещаниям быстрых денег. Ищи действие, которое можно проверить без риска.

⚡ План на вечер:
1. Проверь одну подписку, которую можно отменить.
2. Найди один сервис с кэшбэком или скидкой.
3. Выпиши одну микрозадачу для фриланса.
4. Сохрани площадку, где есть реальные заказы.

Не покупай курсы и не лезь в мутные схемы. Сначала проверь один маленький шаг своими руками.

Что разобрать глубже: фриланс, нейросети или экономию?""",
            "mistake": f"""🚫 Ошибка в теме «{pillar}» — ждать идеальную идею.

Первые деньги чаще приходят от маленькой понятной услуги, а не от красивой стратегии.

⚡ Что сделать:
1. Возьми задачу на 30-60 минут.
2. Опиши результат, который отдашь человеку.
3. Не обещай доход. Обещай конкретную работу.
4. Собери 3 диалога и посмотри, где есть спрос.

{cta}

Что тебе ближе: сделать услугу или сначала сэкономить на подписках?""",
            "experiment": f"""🧪 Эксперимент на вечер: проверь «{pillar}» без риска и сказок.

Цель не заработать миллион. Цель понять, где есть реальный спрос или реальная экономия.

⚡ Сделай так:
1. Выбери один навык или одну регулярную трату.
2. Найди 5 примеров: кто продает похожую услугу или где можно платить меньше.
3. Запиши, что именно люди покупают или отменяют.
4. Сформулируй один маленький шаг на завтра.

Если шаг нельзя сделать за час, он слишком большой.

Что проверишь первым: навык, подписку или сервис с кэшбэком?""",
            "poll": f"""💬 Выбираем следующий разбор по теме «{pillar}».

А — как найти первую микрозадачу на фрилансе.
Б — как использовать нейросеть без «магии» и лишних подписок.
В — где искать кэшбэк и не попасть на мусорные условия.
Г — как урезать расходы на тарифах и сервисах.

⚡ Разберу вариант, который наберет больше ответов: пошагово, без обещаний легких денег и без серых схем.

Можно выбрать не «самый прибыльный» вариант, а тот, который ты реально готов проверить за вечер.

Какая буква тебе сейчас нужнее?""",
            "before_after": f"""🔁 До: ты читаешь советы про «{pillar}» и сохраняешь их в никуда.

После: у тебя есть один проверяемый финансовый шаг.

⚡ Переводим в действие:
1. «Хочу заработать» → «могу сделать вот такую маленькую услугу».
2. «Хочу экономить» → «проверяю одну подписку или тариф».
3. «Хочу нейросети» → «делаю один результат для портфолио».
4. «Хочу кэшбэк» → «сравниваю условия перед покупкой».

Деньги любят конкретику, а не папку с сохраненками.

Какой пункт тебе ближе прямо сейчас?""",
            "script": f"""🗣 Скрипт первого сообщения, если хочешь проверить «{pillar}» через услугу.

Без спама. Без обещаний золотых гор.

⚡ Текст:
«Привет. Я могу помочь с [конкретная задача]. Сделаю маленький тестовый результат: [что именно]. Если зайдет — обсудим дальше».

Перед отправкой проверь:
1. Понятно ли, что человек получит.
2. Нет ли обещания дохода.
3. Можно ли выполнить это быстро.
4. Есть ли пример или черновик.

Кому проще написать первым: знакомому, локальному бизнесу или в чат с заказами?""",
            "resource": f"""🧰 Набор для темы «{pillar}», чтобы не утонуть в советах.

Тебе нужны не сто сервисов, а три проверки.

⚡ Проверь:
1. Таблица расходов — чтобы видеть, где утекают деньги.
2. Один сервис сравнения тарифов или подписок.
3. Одна площадка с микрозадачами.
4. Один AI-инструмент, который реально ускоряет результат.

Если инструмент не дает понятный итог за вечер, отложи его.

Что разобрать отдельным постом: таблицу расходов, микрозадачи или AI-инструменты?""",
        }
        return variants.get(angle, variants["checklist"]).strip()

    def _core_fallback(self, pillar: str, cta: str, angle: str) -> str:
        variants = {
            "myth": f"""🧩 Если задача по теме «{pillar}» висит в голове, она будет давить сильнее, чем есть на самом деле.

Нужно вынести ее в короткую схему. Не идеально. Достаточно понятно, чтобы сделать первый шаг.

⚡ Шаблон:
1. Что должно получиться на выходе?
2. Какие данные уже есть?
3. Какой минимальный результат нужен сегодня?
4. Что мешает начать?
5. Кому и что нужно отправить дальше?

{cta}

Какую задачу разложить по этой схеме первой?""".strip()
,
            "checklist": f"""✅ Чек-лист для темы «{pillar}».

Не начинай с большого плана. Начни с карты ближайшего действия.

⚡ Заполни пять строк:
1. Результат на выходе.
2. Первый шаг на 15 минут.
3. Что нужно запросить у другого человека.
4. Что можно убрать из задачи.
5. Когда проверить прогресс.

{cta}

Какой пункт у тебя чаще всего провисает?""",
            "mistake": f"""🚫 Ошибка в теме «{pillar}» — делать шаблон красивым раньше, чем полезным.

Шаблон должен снимать нагрузку, а не превращаться в дизайнерскую игрушку.

⚡ Проверь:
1. Он помогает принять решение?
2. В нем есть следующий шаг?
3. Его можно заполнить за 10 минут?
4. После заполнения понятно, кому что отправить?

Если нет, режем лишнее.

Какой шаблон нужен первым: задачи, деньги или контент?""",
            "experiment": f"""🧪 Мини-эксперимент для темы «{pillar}».

Возьми одну зависшую задачу и прогони ее через короткий протокол.

⚡ Протокол:
1. Выпиши задачу одной строкой.
2. Укажи, что уже готово.
3. Отметь главный стопор.
4. Выбери действие на 20 минут.
5. После действия реши: продолжать, делегировать или закрыть.

{cta}

Какую зависшую задачу прогнать первой?""",
            "poll": f"""💬 Что разобрать внутри «{pillar}» глубже?

А — шаблон постановки задачи.
Б — чек-лист запуска маленького проекта.
В — разбор хаоса в заметках.
Г — план действий на неделю.

⚡ Выберу самый частый вариант и дам готовую структуру, которую можно сразу забрать в Notion или Google Docs.

Какая буква сейчас полезнее?""",
            "before_after": f"""🔁 До: задача по теме «{pillar}» выглядит как туман.

После: есть маршрут, срок и следующий человек, которому нужно что-то отправить.

⚡ Перевод:
1. «Надо разобраться» → «нужен список решений».
2. «Надо сделать» → «первый черновик до вечера».
3. «Надо подумать» → «выписать 3 варианта и выбрать один».
4. «Потом» → «контрольная точка завтра».

{cta}

Какой туман сейчас надо превратить в маршрут?""",
        }
        return variants.get(angle, variants["checklist"]).strip()
