from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .admin_bot import AdminBot
from .bot_client import TelegramBotClient
from .content_agent import ContentAgent
from .db import ContentItem, ContentStore
from .post_improver import TgPostAIImprover
from .scheduler import build_schedule_slots
from .settings import get_channel, load_config, load_settings
from .telegram_client import TelegramGridClient
from .youtube_source import fetch_youtube_transcript


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="tg-grid")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    login_parser = subparsers.add_parser("login")
    login_parser.add_argument("--phone")
    login_parser.add_argument("--code")
    login_parser.add_argument("--password")

    dialogs_parser = subparsers.add_parser("list-dialogs")
    dialogs_parser.add_argument("--limit", type=int, default=50)

    subparsers.add_parser("bot-check")
    subparsers.add_parser("bot-updates")

    admin_parser = subparsers.add_parser("run-admin-bot")
    admin_parser.add_argument("--config", default="config.yaml")
    admin_parser.add_argument("--once", action="store_true")

    generate_parser = subparsers.add_parser("generate-posts")
    generate_parser.add_argument("--config", default="config.yaml")
    generate_parser.add_argument("--channel", required=True)
    generate_parser.add_argument("--count", type=int, default=10)

    youtube_parser = subparsers.add_parser("generate-from-youtube")
    youtube_parser.add_argument("--config", default="config.yaml")
    youtube_parser.add_argument("--channel", required=True)
    youtube_parser.add_argument("--url")
    youtube_parser.add_argument("--transcript-file")
    youtube_parser.add_argument("--title")
    youtube_parser.add_argument("--count", type=int, default=7)

    list_parser = subparsers.add_parser("list-items")
    list_parser.add_argument("--status")
    list_parser.add_argument("--channel")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--show-creative", action="store_true")

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("--ids", required=True, help="Comma-separated IDs, e.g. 1,2,3")
    approve_parser.add_argument("--config", default="config.yaml")
    approve_parser.add_argument("--skip-improve", action="store_true")

    schedule_parser = subparsers.add_parser("schedule-approved")
    schedule_parser.add_argument("--config", default="config.yaml")
    schedule_parser.add_argument("--channel", required=True)
    schedule_parser.add_argument("--limit", type=int, default=10)

    publisher_parser = subparsers.add_parser("run-publisher")
    publisher_parser.add_argument("--config", default="config.yaml")
    publisher_parser.add_argument("--once", action="store_true")
    publisher_parser.add_argument("--interval", type=int, default=60)
    publisher_parser.add_argument("--limit", type=int, default=20)
    publisher_parser.add_argument("--skip-improve", action="store_true")

    run_all_parser = subparsers.add_parser("run-all")
    run_all_parser.add_argument("--config", default="config.yaml")
    run_all_parser.add_argument("--publisher-interval", type=int, default=60)
    run_all_parser.add_argument("--publisher-limit", type=int, default=20)
    run_all_parser.add_argument("--skip-improve", action="store_true")

    video_parser = subparsers.add_parser("video-ideas")
    video_parser.add_argument("--config", default="config.yaml")
    video_parser.add_argument("--topic", required=True)
    video_parser.add_argument("--count", type=int, default=10)

    creative_parser = subparsers.add_parser("render-creative")
    creative_parser.add_argument("--id", type=int, required=True)
    creative_parser.add_argument("--out-dir", default="creatives")
    creative_parser.add_argument("--size", default="1024x1024")

    args = parser.parse_args()
    telegram_commands = {
        "login",
        "list-dialogs",
        "bot-check",
        "bot-updates",
        "run-admin-bot",
        "schedule-approved",
        "run-publisher",
        "run-all",
    }
    settings = load_settings(require_telegram=args.command in telegram_commands)
    store = ContentStore(settings.db_path)

    if args.command == "init-db":
        store.init()
        print(f"Initialized database: {settings.db_path}")
        return

    if args.command == "login":
        tg = TelegramGridClient(settings)
        if args.code:
            asyncio.run(tg.confirm_login_code(args.code, args.password))
            print("Telegram session is ready.")
        elif args.phone:
            asyncio.run(tg.request_login_code(args.phone))
            print("Telegram sent a login code. Re-run login with --code.")
        else:
            raise RuntimeError("Pass --phone to request a code or --code to confirm login.")
        return

    if args.command == "list-dialogs":
        tg = TelegramGridClient(settings)
        dialogs = asyncio.run(tg.list_dialogs(args.limit))
        for dialog in dialogs:
            username = f"@{dialog['username']}" if dialog["username"] else ""
            print(f"{dialog['name']} | id={dialog['id']} | {username} | channel={dialog['is_channel']}")
        return

    if args.command == "bot-check":
        bot = TelegramBotClient(settings.telegram_bot_token)
        me = bot.get_me()
        print(f"Bot OK: @{me.get('username')} | id={me.get('id')}")
        return

    if args.command == "bot-updates":
        bot = TelegramBotClient(settings.telegram_bot_token)
        for update in bot.get_updates():
            print(update)
        return

    if args.command == "run-admin-bot":
        store.init()
        config = load_config(args.config)
        bot = TelegramBotClient(settings.telegram_bot_token)
        AdminBot(bot, store, settings, config, config.get("channels", [])).run(once=args.once)
        return

    if args.command == "generate-posts":
        store.init()
        config = load_config(args.config)
        channel = get_channel(config, args.channel)
        agent = build_content_agent(settings)
        items = agent.generate_posts(config, channel, args.count)
        ids = store.add_many(args.channel, items)
        print(f"Generated {len(ids)} drafts: {','.join(map(str, ids))}")
        return

    if args.command == "generate-from-youtube":
        store.init()
        if not args.url and not args.transcript_file:
            raise RuntimeError("Pass --url or --transcript-file.")

        config = load_config(args.config)
        channel = get_channel(config, args.channel)
        if args.transcript_file:
            transcript = Path(args.transcript_file).read_text(encoding="utf-8")
            source_url = args.url
        else:
            transcript = fetch_youtube_transcript(args.url)
            source_url = args.url

        agent = build_content_agent(settings)
        items = agent.generate_posts_from_source(
            config=config,
            channel=channel,
            transcript=transcript,
            count=args.count,
            source_title=args.title,
            source_url=source_url,
        )
        ids = store.add_many(args.channel, items)
        print(f"Generated {len(ids)} YouTube-based drafts: {','.join(map(str, ids))}")
        return

    if args.command == "list-items":
        store.init()
        items = store.list_items(args.status, args.channel, args.limit)
        print_items(items, show_creative=args.show_creative)
        return

    if args.command == "approve":
        store.init()
        ids = parse_ids(args.ids)
        if not args.skip_improve:
            config = load_config(args.config)
            improver = TgPostAIImprover(settings, config)
            for item in store.get_items_by_ids(ids):
                improver.improve_item(store, item)
        count = store.approve(ids)
        print(f"Approved {count} item(s).")
        return

    if args.command == "schedule-approved":
        store.init()
        config = load_config(args.config)
        channel = get_channel(config, args.channel)
        calendar = config.get("calendar", {})
        timezone = calendar.get("timezone", settings.timezone)
        slots = calendar.get("slots", [])
        approved = list(reversed(store.list_items("approved", args.channel, args.limit)))
        schedule = build_schedule_slots(len(approved), slots, timezone)
        mode = resolve_publish_mode(settings)
        if mode == "bot":
            for item, scheduled_at in zip(approved, schedule, strict=True):
                store.assign_schedule(item.id, scheduled_at.isoformat())
            print(f"Queued {len(approved)} item(s) for local bot publisher.")
        else:
            tg = TelegramGridClient(settings)
            asyncio.run(schedule_items(store, tg, channel["peer"], approved, schedule))
            print(f"Scheduled {len(approved)} item(s) in Telegram.")
        return

    if args.command == "run-publisher":
        store.init()
        config = load_config(args.config)
        channel_peers = {
            channel["key"]: channel["peer"]
            for channel in config.get("channels", [])
            if channel.get("key") and channel.get("peer")
        }
        bot = TelegramBotClient(settings.telegram_bot_token)
        improver = None if args.skip_improve else TgPostAIImprover(settings, config)
        run_bot_publisher(store, bot, channel_peers, improver, args.once, args.interval, args.limit)
        return

    if args.command == "run-all":
        store.init()
        config = load_config(args.config)
        bot = TelegramBotClient(settings.telegram_bot_token)
        channel_peers = {
            channel["key"]: channel["peer"]
            for channel in config.get("channels", [])
            if channel.get("key") and channel.get("peer")
        }
        improver = None if args.skip_improve else TgPostAIImprover(settings, config)
        publisher_thread = threading.Thread(
            target=run_bot_publisher,
            args=(
                store,
                bot,
                channel_peers,
                improver,
                False,
                args.publisher_interval,
                args.publisher_limit,
            ),
            daemon=True,
        )
        publisher_thread.start()
        AdminBot(bot, store, settings, config, config.get("channels", [])).run()
        return

    if args.command == "video-ideas":
        config = load_config(args.config)
        agent = build_content_agent(settings)
        ideas = agent.generate_video_ideas(config, args.topic, args.count)
        for index, idea in enumerate(ideas, start=1):
            print(f"\n#{index} {idea.get('platform', 'Video')}: {idea.get('hook', 'Untitled')}")
            outline = idea.get("outline", [])
            if isinstance(outline, list):
                for step in outline:
                    print(f"- {step}")
            else:
                print(outline)
            if idea.get("production_notes"):
                print(f"Production: {idea['production_notes']}")
            if idea.get("repurpose_to_telegram"):
                print(f"Telegram: {idea['repurpose_to_telegram']}")
        return

    if args.command == "render-creative":
        store.init()
        item = store.get_items_by_ids([args.id])[0]
        if not item.creative_prompt:
            raise RuntimeError(f"Item {args.id} has no creative_prompt.")
        agent = build_content_agent(settings)
        output_path = agent.render_creative(
            prompt=item.creative_prompt,
            output_path=Path(args.out_dir) / f"creative_{item.id}.png",
            size=args.size,
        )
        store.mark_creative_rendered(item.id, str(output_path))
        print(f"Saved creative: {output_path}")
        return


async def schedule_items(
    store: ContentStore,
    tg: TelegramGridClient,
    peer: str,
    items: list[ContentItem],
    schedule: list,
) -> None:
    for item, scheduled_at in zip(items, schedule, strict=True):
        try:
            message_id = await tg.schedule_message(
                peer=peer,
                message=item.body,
                scheduled_at=scheduled_at.astimezone(UTC),
            )
            store.mark_scheduled(item.id, scheduled_at.isoformat(), message_id)
        except Exception as exc:
            store.mark_failed(item.id, str(exc))
            raise


def print_items(items: Iterable[ContentItem], show_creative: bool = False) -> None:
    for item in items:
        print(f"\n[{item.id}] {item.status} | {item.channel_key} | {item.title}")
        if item.scheduled_at:
            print(f"Scheduled: {item.scheduled_at}")
        print(item.body)
        if show_creative and item.creative_prompt:
            print("\nCreative prompt:")
            print(item.creative_prompt)
        if show_creative and item.creative_path:
            print(f"Creative file: {item.creative_path}")


def parse_ids(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def build_content_agent(settings) -> ContentAgent:
    return ContentAgent(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        image_model=settings.openai_image_model,
        base_url=settings.openai_base_url,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.tgpostai_model,
    )


def resolve_publish_mode(settings) -> str:
    if settings.telegram_publish_mode in {"bot", "user"}:
        return settings.telegram_publish_mode
    if settings.telegram_bot_token:
        return "bot"
    return "user"


def run_bot_publisher(
    store: ContentStore,
    bot: TelegramBotClient,
    channel_peers: dict[str, str],
    improver: TgPostAIImprover | None,
    once: bool,
    interval: int,
    limit: int,
) -> None:
    while True:
        due = store.list_due_items(datetime.now(UTC).isoformat(), limit=limit)
        for item in due:
            try:
                peer = channel_peers.get(item.channel_key)
                if not peer:
                    raise RuntimeError(f"No peer configured for channel key '{item.channel_key}'.")
                if improver:
                    item = improver.improve_item(store, item)
                message_id = bot.send_message(peer, item.body)
                store.mark_published(item.id, message_id)
                print(f"Published item {item.id}")
            except Exception as exc:
                store.mark_failed(item.id, str(exc))
                print(f"Failed item {item.id}: {exc}")

        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
