from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from telethon.errors import SessionPasswordNeededError
from telethon import TelegramClient

from .settings import RuntimeSettings


class TelegramGridClient:
    def __init__(self, settings: RuntimeSettings):
        if settings.telegram_api_id is None or not settings.telegram_api_hash:
            raise RuntimeError("Telegram credentials are required for this command.")

        self.session_path = settings.session_dir / settings.telegram_session_name
        self.login_state_path = settings.session_dir / f"{settings.telegram_session_name}.login.json"
        self.client = TelegramClient(
            str(self.session_path),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    async def login(self, phone: str | None = None) -> None:
        await self.client.start(phone=phone)

    async def request_login_code(self, phone: str) -> None:
        await self.client.connect()
        sent = await self.client.send_code_request(phone)
        self.login_state_path.write_text(
            json.dumps(
                {
                    "phone": phone,
                    "phone_code_hash": sent.phone_code_hash,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        await self.client.disconnect()

    async def confirm_login_code(self, code: str, password: str | None = None) -> None:
        if not self.login_state_path.exists():
            raise RuntimeError("No pending login state. Run login --phone first.")

        state = json.loads(self.login_state_path.read_text(encoding="utf-8"))
        await self.client.connect()
        try:
            await self.client.sign_in(
                phone=state["phone"],
                code=code,
                phone_code_hash=state["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            if not password:
                raise RuntimeError("Telegram 2FA password is required. Re-run with --password.")
            await self.client.sign_in(password=password)
        finally:
            await self.client.disconnect()

        self.login_state_path.unlink(missing_ok=True)

    async def list_dialogs(self, limit: int = 50) -> list[dict]:
        await self.client.start()
        dialogs = await self.client.get_dialogs(limit=limit)
        result = []
        for dialog in dialogs:
            entity = dialog.entity
            result.append(
                {
                    "name": dialog.name,
                    "id": getattr(entity, "id", None),
                    "username": getattr(entity, "username", None),
                    "is_channel": getattr(entity, "broadcast", False),
                }
            )
        return result

    async def schedule_message(
        self,
        peer: str,
        message: str,
        scheduled_at: datetime,
        media_path: str | None = None,
    ) -> int | None:
        await self.client.start()
        entity = await self.client.get_entity(peer)
        file = Path(media_path) if media_path else None
        sent = await self.client.send_message(
            entity,
            message,
            file=str(file) if file else None,
            schedule=scheduled_at,
            link_preview=False,
        )
        return getattr(sent, "id", None)
