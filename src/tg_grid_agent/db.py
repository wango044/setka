from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    creative_prompt TEXT,
    creative_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    telegram_message_id INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_content_status
ON content_items(status, channel_key, scheduled_at);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_sessions (
    chat_id INTEGER PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ContentItem:
    id: int
    channel_key: str
    title: str
    body: str
    creative_prompt: str | None
    creative_path: str | None
    status: str
    scheduled_at: str | None
    telegram_message_id: int | None
    metadata: dict
    created_at: str
    updated_at: str


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ContentStore:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def add_many(self, channel_key: str, items: Iterable[dict]) -> list[int]:
        ids: list[int] = []
        timestamp = now_iso()
        with self.connect() as conn:
            for item in items:
                cursor = conn.execute(
                    """
                    INSERT INTO content_items (
                        channel_key, title, body, creative_prompt, creative_path, status,
                        metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, NULL, 'draft', ?, ?, ?)
                    """,
                    (
                        channel_key,
                        item["title"],
                        item["body"],
                        item.get("creative_prompt"),
                        json.dumps(item.get("metadata", {}), ensure_ascii=False),
                        timestamp,
                        timestamp,
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def list_items(
        self,
        status: str | None = None,
        channel_key: str | None = None,
        limit: int = 50,
    ) -> list[ContentItem]:
        clauses: list[str] = []
        params: list[object] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if channel_key:
            clauses.append("channel_key = ?")
            params.append(channel_key)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM content_items
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_items_by_ids(self, ids: Iterable[int]) -> list[ContentItem]:
        id_list = list(ids)
        if not id_list:
            return []

        placeholders = ",".join("?" for _ in id_list)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM content_items WHERE id IN ({placeholders}) ORDER BY id",
                id_list,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def approve(self, ids: Iterable[int]) -> int:
        return self._set_status(ids, "approved")

    def mark_scheduled(
        self,
        item_id: int,
        scheduled_at: str,
        telegram_message_id: int | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET status = 'scheduled',
                    scheduled_at = ?,
                    telegram_message_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (scheduled_at, telegram_message_id, now_iso(), item_id),
            )

    def assign_schedule(self, item_id: int, scheduled_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET status = 'queued',
                    scheduled_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (scheduled_at, now_iso(), item_id),
            )

    def list_due_items(self, now: str, limit: int = 20) -> list[ContentItem]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM content_items
                WHERE status = 'queued'
                  AND scheduled_at <= ?
                ORDER BY scheduled_at ASC, id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def mark_published(self, item_id: int, telegram_message_id: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET status = 'published',
                    telegram_message_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (telegram_message_id, now_iso(), item_id),
            )

    def mark_creative_rendered(self, item_id: int, creative_path: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET creative_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (creative_path, now_iso(), item_id),
            )

    def update_body(self, item_id: int, body: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET body = ?, updated_at = ?
                WHERE id = ?
                """,
                (body, now_iso(), item_id),
            )

    def update_body_and_metadata(self, item_id: int, body: str, metadata: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET body = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (body, json.dumps(metadata, ensure_ascii=False), now_iso(), item_id),
            )

    def update_metadata(self, item_id: int, metadata: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(metadata, ensure_ascii=False), now_iso(), item_id),
            )

    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_bot_session(self, chat_id: int) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM bot_sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return json.loads(row["state_json"]) if row else {}

    def set_bot_session(self, chat_id: int, state: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_sessions (chat_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (chat_id, json.dumps(state, ensure_ascii=False), now_iso()),
            )

    def mark_failed(self, item_id: int, error: str) -> None:
        item = self.get_items_by_ids([item_id])[0]
        metadata = dict(item.metadata)
        metadata["last_error"] = error
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET status = 'failed', metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(metadata, ensure_ascii=False), now_iso(), item_id),
            )

    def _set_status(self, ids: Iterable[int], status: str) -> int:
        id_list = list(ids)
        if not id_list:
            return 0
        placeholders = ",".join("?" for _ in id_list)
        with self.connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE content_items
                SET status = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [status, now_iso(), *id_list],
            )
            return cursor.rowcount

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ContentItem:
        return ContentItem(
            id=row["id"],
            channel_key=row["channel_key"],
            title=row["title"],
            body=row["body"],
            creative_prompt=row["creative_prompt"],
            creative_path=row["creative_path"],
            status=row["status"],
            scheduled_at=row["scheduled_at"],
            telegram_message_id=row["telegram_message_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
