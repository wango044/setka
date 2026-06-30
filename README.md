# TG Grid Agent

MVP-агент для сетки Telegram-каналов: генерирует посты, идеи для TikTok/YouTube, хранит контент в SQLite и планирует публикации через Telegram user-session.

## Почему не управление открытым Telegram

Управление уже запущенным окном Telegram через клики будет ломаться от обновлений интерфейса, фокуса окна и случайных попапов. Этот проект использует Telegram API через отдельную локальную session-файл авторизованного аккаунта. Аккаунт должен быть админом каналов, куда агент будет постить.

## Быстрый старт

1. Самый простой путь: создай бота через `@BotFather`, добавь его админом в каналы и заполни `TELEGRAM_BOT_TOKEN`.
2. Если нужен именно user-session, создай Telegram API credentials на `https://my.telegram.org` и заполни `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`.
3. Скопируй `.env.example` в `.env` и заполни `OPENAI_API_KEY`.
3. Скопируй `config.example.yaml` в `config.yaml` и укажи свои каналы.
4. Установи зависимости:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

5. Инициализируй базу. Для bot-mode логин не нужен:

```powershell
tg-grid init-db
```

Для user-session дополнительно войди в Telegram:

```powershell
tg-grid login --phone +79990000000
```

6. Сгенерируй 10 постов вперед:

```powershell
tg-grid generate-posts --config config.yaml --channel main --count 10
```

7. Посмотри черновики:

```powershell
tg-grid list-items --status draft
```

8. Одобри черновики и поставь в расписание:

```powershell
tg-grid approve --ids 1,2,3,4,5,6,7,8,9,10
tg-grid schedule-approved --config config.yaml --channel main
```

В bot-mode запусти локальный publisher, который будет отправлять посты в нужное время:

```powershell
tg-grid run-publisher
```

Или запусти админ-панель и publisher одним процессом:

```powershell
tg-grid run-all --config config.yaml
```

## Идеи для TikTok и YouTube

```powershell
tg-grid video-ideas --config config.yaml --topic "прогрев аудитории для запуска продукта" --count 12
```

## Креативы

MVP генерирует production-ready промпты для обложек, карточек и видео-сцен, а также может сразу сохранить картинку по промпту:

```powershell
tg-grid list-items --status draft --show-creative
tg-grid render-creative --id 1
```

## Автоулучшение постов через TgPostAI

Перед одобрением постов агент может прогонять текст через TgPostAI-style polish на Gemini:

```env
GEMINI_API_KEY=...
TGPOSTAI_MODEL=gemini-2.5-flash
```

Когда включено `generation.improve_before_approval: true`, кнопка `Одобрить` в Telegram-админке сначала улучшает пост, сохраняет оригинал в metadata, а потом переводит пост в зеленый статус. Вручную улучшить пост можно кнопкой `Улучшить`.

CLI тоже использует улучшение:

```powershell
tg-grid approve --ids 1,2,3
```

Если нужно одобрить без AI-polish:

```powershell
tg-grid approve --ids 1,2,3 --skip-improve
```

## Безопасность

- Не публикуй без ручного одобрения, пока не доверяешь стилю агента.
- Не храни `.env` и `sessions/*.session` в Git.
- Учитывай лимиты Telegram и не превращай сетку в спам-рассылку.

## Деплой

В репозитории есть `Dockerfile` и `render.yaml` для Render Background Worker. Worker запускает:

```bash
tg-grid run-all --config config.yaml
```

На Render нужно добавить secret env vars:

```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
```

SQLite база хранится на persistent disk по пути `/data/tg_grid.sqlite3`.
