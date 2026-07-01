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
            improved_body = self.improve_text(item.body, channel)
            if improved_body and improved_body.strip() and improved_body.strip() != item.body.strip():
                metadata.setdefault("original_body", item.body)
                metadata["tgpostai_improved"] = True
                metadata["tgpostai_model"] = self.settings.tgpostai_model
                metadata["tgpostai_force"] = force
                store.update_body_and_metadata(item.id, improved_body.strip(), metadata)
            else:
                metadata["tgpostai_improved"] = False
                metadata["tgpostai_note"] = "Model returned unchanged text."
                store.update_metadata(item.id, metadata)
        except Exception as exc:
            metadata["tgpostai_error"] = str(exc)
            store.update_metadata(item.id, metadata)

        return store.get_items_by_ids([item.id])[0]

    def improve_text(self, text: str, channel: dict[str, Any]) -> str:
        if not self.settings.gemini_api_key:
            return text

        prompt = self._prompt(text, channel)
        model = urllib.parse.quote(self.settings.tgpostai_model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={urllib.parse.quote(self.settings.gemini_api_key)}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.55,
                "topP": 0.9,
                "maxOutputTokens": 1200,
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

    def _prompt(self, text: str, channel: dict[str, Any]) -> str:
        brand = self.config.get("brand", {})
        max_chars = self.config.get("generation", {}).get("max_post_chars", 900)
        return f"""
Improve this Telegram post before publication.
Return ONLY the final improved post text. No comments, no markdown fences.

Language: Russian.
Max length: {max_chars} characters.

Style:
- дерзко, экспертно, по делу;
- короткие предложения;
- без воды;
- emoji at the start of paragraphs when natural;
- finish with a question to the audience;
- no clickbait;
- do not invent facts, numbers, cases, prices, or guarantees;
- preserve the original meaning and CTA;
- keep it safe for a public Telegram channel.

Brand:
{json.dumps(brand, ensure_ascii=False)}

Channel:
{json.dumps(channel, ensure_ascii=False)}

Original post:
{text}
""".strip()
