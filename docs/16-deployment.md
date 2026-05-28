# 16. Развертывание и эксплуатация

## .env

Конфигурация в `.env` (см. [`.env.example`](../.env.example)):

```ini
BOT_TOKEN=your_telegram_bot_token

# PostgreSQL (для прод-деплоя — имя контейнера в docker network)
POSTGRES_DB=mood_tracker
POSTGRES_USER=mood_user
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

DATABASE_URL=postgresql://mood_user:change_me@postgres:5432/mood_tracker

DEFAULT_TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO

# Опциональный SOCKS5 прокси для Telegram API
# HTTPS_PROXY=socks5://user:pass@host:port
```

Используется через `python-dotenv` (`load_dotenv()` в [`bot/config.py`](../bot/config.py)).

## Локальный запуск

```bash
conda activate basic  # или venv
pip install -r requirements.txt

cp .env.example .env
# Отредактировать BOT_TOKEN и DATABASE_URL

# PostgreSQL должен быть запущен и доступен по DATABASE_URL.

# Применить миграции
alembic upgrade head

# Запустить бота
python -m bot.main
```

## Docker

Dockerfile ([`Dockerfile`](../Dockerfile)):
- `python:3.11-slim` базовый образ.
- Устанавливает `build-essential`, `libpq-dev`, `tzdata` (нужен для zoneinfo).
- `pip install -r requirements.txt`.
- `CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]` — миграции и старт при каждом запуске.

docker-compose.yml ([`docker-compose.yml`](../docker-compose.yml)):
- Использует образ из ghcr.io: `ghcr.io/watermellon2018/mood_tracker_bot:${BOT_TAG:-latest}`.
- `restart: always`.
- `env_file: .env`.
- Подключается к внешней сети `postgres_net` (PostgreSQL — отдельный контейнер).
- Healthcheck — простая проверка Python.

### Сборка и запуск

```bash
cp .env.example .env
# отредактируй BOT_TOKEN и POSTGRES_PASSWORD

docker compose up -d --build
```

### Логи

```bash
docker compose logs -f mood_tracker_bot
```

### Ручные миграции

```bash
docker compose exec mood_tracker_bot alembic upgrade head
docker compose exec mood_tracker_bot alembic revision --autogenerate -m "description"
```

### Остановка

```bash
docker compose down
```

## Зависимости

`requirements.txt`:

```
python-telegram-bot[job-queue,socks]==21.6
httpx[socks]==0.27.2
SQLAlchemy==2.0.35
psycopg2-binary==2.9.9
alembic==1.13.3
pandas==2.2.3
matplotlib==3.9.2
openpyxl==3.1.5
python-dotenv==1.0.1
pytz==2024.2
```

`[job-queue]` — extras, активирующий JobQueue в PTB (нужен `APScheduler` внутри, но обвязка спрятана за PTB).

`[socks]` — поддержка SOCKS5 прокси через httpx.

## Alembic

Конфиг: [`alembic.ini`](../alembic.ini) + [`migrations/env.py`](../migrations/env.py).

- Все миграции в `migrations/versions/0001_...` через `0011_...`.
- Используют `Base.metadata` из `bot.database` (для autogenerate).
- DATABASE_URL берётся из `.env` через `bot.config`.

### Создание новой миграции

```bash
alembic revision --autogenerate -m "describe change"
# Прочесть сгенерированный файл, при необходимости подредактировать.
alembic upgrade head
```

Рекомендации:
- Использовать `IF NOT EXISTS` / `IF EXISTS` для ALTER (идемпотентность).
- Для seed-данных писать UPDATE WHERE code IN (...).
- Не делать destructive миграции без явного бэкфилла.

## Прокси

Если бот развёрнут в регионе с ограниченным доступом к api.telegram.org — `HTTPS_PROXY` в `.env`:

```ini
HTTPS_PROXY=socks5://user:pass@host:1080
```

В [`bot/main.py`](../bot/main.py):
```python
if config.HTTPS_PROXY:
    builder = builder.proxy(config.HTTPS_PROXY).get_updates_proxy(config.HTTPS_PROXY)
```

PTB передаёт proxy в `Request` объекты для get_updates и send-операций.

## Логирование

LOG_LEVEL из `.env`, default `INFO`. Уровни:

- `INFO` — старт, регистрации, изменения настроек, отправка опросов, рендер статистики.
- `WARNING` — попытки доступа к чужим id, fallback'ы.
- `ERROR` — IntegrityError, DB ошибки, ошибки графиков.

`httpx` и `apscheduler` принудительно на `WARNING` (иначе много шума).

## Health-проверка

Для production-окружения README рекомендует регулярный health-check соединения с БД — пока не реализован. JobQueue-задачи логируют свои ошибки, но автоматического алертинга нет.

## Persistent state

ConversationHandler не персистентный (`persistent=False`). При рестарте бота:
- Расписание восстанавливается (`reschedule_all` в `post_init`).
- pending_surveys в `pending` или `reminder_sent` остаются в БД, но reminder-jobs (которые в JobQueue памяти) теряются. Через час `cleanup_expired_pendings` пометит истёкшие как `expired`.
- Опросы, начатые до рестарта, но не завершённые — теряются (state в `user_data`).

## Не-цели

- ❌ Webhook-режим — только polling (`run_polling(drop_pending_updates=True)`).
- ❌ Cluster-safe scheduling.
- ❌ Автоматическое масштабирование.
- ❌ Backup БД (отдельная задача администратора).

## Связанные документы

- [01-overview.md](01-overview.md) — стек.
- [13-database-schema.md](13-database-schema.md) — миграции.
- [10-scheduling-reminders.md](10-scheduling-reminders.md) — JobQueue.
